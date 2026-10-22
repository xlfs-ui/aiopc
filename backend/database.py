"""Local SQLite backup and migration commands. Never prints account records."""
import argparse
import json
import sqlite3
from datetime import datetime
from app import storage


def main():
    parser=argparse.ArgumentParser(description='SQLite backup and migration')
    parser.add_argument('action',choices=['backup','migrate','info','seed-demo'])
    args=parser.parse_args()
    if args.action=='seed-demo':
        from app import main as application
        from app.demo_seed import seed_demo
        result=seed_demo()
        print(json.dumps({'batch':result['batch'],'counts':result['counts'],'reports':result['reports']},ensure_ascii=True,indent=2))
        return
    if storage.is_postgres():
        if args.action=='backup': parser.error('Cloud Postgres backups require Neon snapshots or pg_dump; this command only backs up local SQLite')
        if args.action=='migrate':
            from app import main as application
        with storage.connection() as db:
            result={'storage':'postgresql','schema_version':db.execute('SELECT MAX(version) FROM schema_versions').fetchone()[0],'business_rows':{table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in storage.BUSINESS},'documents':db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],'chunks':db.execute('SELECT COUNT(*) FROM retrieval_chunks').fetchone()[0]}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.action=='backup':
        if not storage.DB_PATH.exists(): parser.error('Database does not exist; start the backend first')
        target=storage.DB_PATH.with_name(storage.DB_PATH.stem+'.backup.'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.db')
        source=sqlite3.connect(f'{storage.DB_PATH.as_uri()}?mode=ro',uri=True,timeout=15)
        destination=sqlite3.connect(target)
        try: source.backup(destination)
        finally: destination.close(); source.close()
        print('Backup saved: '+str(target))
        return
    if args.action=='migrate':
        from app import main as application
        print('Migration completed; existing data retained.')
    elif not storage.DB_PATH.exists(): parser.error('Database does not exist')
    db=sqlite3.connect(f'{storage.DB_PATH.as_uri()}?mode=ro',uri=True,timeout=15)
    try:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result={'schema_version':db.execute('PRAGMA user_version').fetchone()[0], 'journal_mode':db.execute('PRAGMA journal_mode').fetchone()[0], 'business_rows':{table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] if table in tables else None for table in storage.BUSINESS}, 'documents':db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] if 'documents' in tables else 0, 'chunks':db.execute('SELECT COUNT(*) FROM retrieval_chunks').fetchone()[0] if 'retrieval_chunks' in tables else 0}
    finally: db.close()
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
