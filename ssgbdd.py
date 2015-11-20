#! /usr/bin/python3
import multiprocessing
import sqlite3
import signal
import metabanco

# Queries uteis:
#   Todas as tabelas: SELECT name FROM sqlite_master WHERE type='table';
#   Descricoes: list(map(lambda x: x[0], cursor.description))


def inicia_banco(db_name):
    db = sqlite3.connect(db_name, isolation_level='EXCLUSIVE',
                         detect_types=sqlite3.PARSE_DECLTYPES)
    test_cur = db.cursor()
    test_cur.execute('''SELECT 1''')  # teste OK
    if not test_cur.fetchone():
        raise Exception('Erro na conexão')
    return db


def db_process(id, comm):
    '''Conecta a um banco Sqlite, testa conexao, envia sinal positivo para
    processo pai e fica aguardando comandos SQL. Se receber 'X',
    encerra conexao.
    '''
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    print('[%d] Iniciando instancia de banco' % id)
    db = inicia_banco('bd' + str(id) + '.db')
    cur = db.cursor()
    comm.send(True)
    while True:
        try:
            # aguarda proxima instrucao
            cmd = comm.recv()
            # processa instrucao
            if cmd == 'X':
                break
            else:
                cur.execute(cmd)
                db.commit()
                comm.send({
                             'dados': cur.fetchall(),
                             'result': True
                          })

        except Exception as e:
            print('[b%d] Erro:', e)
            db.rollback()
            comm.send({
                         'dados': None,
                         'result': False
                      })

    print('[b%d] Encerrando conexao' % id)
    db.close()


def abrir_instancias(inst_num):
    ''' Abre [inst_num] processos que se conectam a bancos diferentes e aguarda
    sinal de conexão pronta e testada de cada um.
    Retorna: lista de processos com "id" e comunicacoes respectivas.
    '''
    instances = list()
    for n in range(inst_num):
        instances.insert(n, dict())
        instances[n]['id'] = n
        instances[n]['comm'], child_conn = multiprocessing.Pipe()
        proc = multiprocessing.Process(target=db_process,
                                       args=(n+1, child_conn))
        proc.start()
        instances[n]['proc'] = proc

    for n in instances:
        if n['comm'].recv():
            # instancia pronta
            pass
    return instances


def interpreta_create(cmd, instances):
    print('')
    # separa regras
    cmd_parts = cmd.partition('PARTITION')
    create_table = cmd_parts[0]
    table_name = None
    try:
        table_name = metabanco.testa_create_table_query(create_table)
        metabanco.cria_metadados(table_name, cmd_parts)
        for i in instances:
            i['comm'].send(create_table)
        for i in instances:
            resp = i['comm'].recv()
            if not resp['result']:
                raise Exception('Falha ao aplicar em instância')

        metabanco.DB.commit()

    except Exception as e:
        print('Erro:', e)
        print('Executando ROLLBACK')
        metabanco.DB.rollback()
        if table_name:
            metabanco.DB.execute('DROP TABLE %s' % table_name)


if __name__ == '__main__':
    print('''
Trabalho de SGBDD
Simples Sistema de Gerenciamento de Banco de Dados Distribuido
    ''')

    print('''
    Iniciando banco principal...
    ''')
    db_meta = inicia_banco('metadados.db')
    metabanco.estrutura_metadados(db_meta)

    while True:
        try:
            i = input('Instancias distribuídas (SITES): ')
            inst_num = int(i)
            if (inst_num < 1):
                print('Precisa ser maior ou igual a 1')
                continue
            break
        except ValueError:
            pass
        except KeyboardInterrupt:
            exit(1)

    instances = abrir_instancias(inst_num)

    menu = {
        'CREATE': interpreta_create,
    }

    print('''
Comandos:
    CREATE TABLE nome_tabela (nome_coluna tipo_coluna, )_
        PARTITION nome_coluna (instância: critério, )
    SAIR
''')

    cmd = None
    while (cmd != 'SAIR'):
        # recebe instrucao
        try:
            cmd = input('> ').upper()
            cmd_type = cmd.partition(' ')[0]
            if (cmd_type in menu):
                menu[cmd_type](cmd, instances)
        except KeyError:
            pass
        except IndexError:
            pass
        except KeyboardInterrupt:
            break

    print('Finalizando')
    db_meta.close()
    for n in instances:
        n['comm'].send('X')
        n['proc'].join()

    print('Fim\n')
