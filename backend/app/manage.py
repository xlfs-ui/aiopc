"""Trusted local administration; passwords are read interactively."""
import argparse
import getpass
import re
from fastapi import HTTPException
from app.auth import create_user, hash_password, validate_password
from app import storage


def main():
    parser=argparse.ArgumentParser(description='Local account administration')
    parser.add_argument('action',choices=['create-admin','reset-password'])
    parser.add_argument('--username',required=True)
    parser.add_argument('--display-name',default='社区管理员')
    args=parser.parse_args()
    username=args.username.lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,31}',username):
        parser.error('Username: 3-32 letters, digits or underscore; start with a letter')
    password=getpass.getpass('New password (12-128 characters): ')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    try:
        validate_password(password,username)
        if args.action == 'create-admin':
            create_user(username,args.display_name,password,role='admin')
        else:
            encoded=hash_password(password)
            with storage.connection(write=True) as db:
                user=db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
                if not user:
                    parser.error('Account not found')
                db.execute('UPDATE users SET password_hash=? WHERE id=?',(encoded,user['id']))
                db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                db.execute('DELETE FROM rate_limits WHERE bucket=?',('login-user:'+username,))
                storage.audit(db,'本机重置密码',user['id'],'local-operator')
    except ValueError as exc:
        parser.error(str(exc))
    except HTTPException as exc:
        parser.error(str(exc.detail))
    print('Account operation completed. Existing sessions were revoked on password reset.')


if __name__ == '__main__':
    main()
