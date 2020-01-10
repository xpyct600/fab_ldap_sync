#!/usr/bin/env python3
import os
import ldap
import logging
from yaml import safe_load
from airflow.www_rbac.app import cached_appbuilder

logger = logging.getLogger(__name__)
f_handler = logging.FileHandler('/var/log/airflow_ldap_sync.log')
f_format = logging.Formatter('%(asctime)s - %(message)s')
f_handler.setFormatter(f_format)
logger.addHandler(f_handler)
logger.info('Starting airflow ldap sync')

group_map_file = os.path.join(os.environ['AIRFLOW_HOME'], 'ldap_sync.yaml')
with open(group_map_file) as f:
    group_map = safe_load(f)

appbuilder = cached_appbuilder()
con = ldap.initialize(appbuilder.sm.auth_ldap_server)
con.set_option(ldap.OPT_REFERRALS, 0)
appbuilder.sm._bind_indirect_user(ldap, con)


for group in group_map:
    filter_str = \
                "(&(ObjectClass=Group)(cn=%s))" % (
                    group
                )
    group_cn = con.search_s(
            appbuilder.sm.auth_ldap_search,
            ldap.SCOPE_SUBTREE,
            filter_str,
            ['cn']
        )[0][0]
    filter_str = \
                "(&(ObjectClass=User)(memberOf=%s))" % (
                    group_cn
                )
    users = con.search_s(
            appbuilder.sm.auth_ldap_search,
            ldap.SCOPE_SUBTREE,
            filter_str,
            [appbuilder.sm.auth_ldap_uid_field]
        )
    user_list = [sam_account_name.get(appbuilder.sm.auth_ldap_uid_field)[0].decode('utf-8') for sam_account_name in [user[1] for user in users]]

    # Adding new users:
    for username in user_list:
        user = appbuilder.sm.find_user(username)
        if not user:
            new_user = appbuilder.sm._search_ldap(ldap, con, username)
            ldap_user_info = new_user[0][1]
            if new_user:
                user = appbuilder.sm.add_user(
                    username=username,
                    first_name=appbuilder.sm.ldap_extract(
                        ldap_user_info,
                        appbuilder.sm.auth_ldap_firstname_field,
                        username
                    ),
                    last_name=appbuilder.sm.ldap_extract(
                        ldap_user_info,
                        appbuilder.sm.auth_ldap_lastname_field,
                        username
                    ),
                    email=appbuilder.sm.ldap_extract(
                        ldap_user_info,
                        appbuilder.sm.auth_ldap_email_field,
                        username + '@email.notfound'
                    ),
                    role=appbuilder.sm.find_role(group_map[group])
                )
                if user:
                    logger.info('User {} created.'.format(user.username))
            else:
                logger.info('AD user {} not found'.format(username))
                
                
ab_user_list = appbuilder.sm.get_all_users()
for user in ab_user_list:
    if appbuilder.sm._search_ldap(ldap, con, user.username):
        # Mapping additional roles:
        filter_str = \
                    "(&(ObjectClass=User)(%s=%s))" % (
                        appbuilder.sm.auth_ldap_uid_field,
                        user.username
                    )
        user_cn = con.search_s(
                appbuilder.sm.auth_ldap_search,
                ldap.SCOPE_SUBTREE,
                filter_str,
                [appbuilder.sm.auth_ldap_uid_field]
            )[0][0]
        filter_str = \
                    "(&(ObjectClass=Group)(member=%s)(cn=airflow*))" % (
                        user_cn
                    )
        groups = con.search_s(
                appbuilder.sm.auth_ldap_search,
                ldap.SCOPE_SUBTREE,
                filter_str,
                ['cn']
            )
        group_list = [cn.get('cn')[0].decode('utf-8') for cn in [group[1] for group in groups]]
        #roles = user.roles
        roles = []
        for group in group_list:
            role = appbuilder.sm.find_role(group_map[group])
            if role:
                roles.append(role)
        user.roles = roles
        appbuilder.sm.update_user(user)

    else:
        # Deleting fired users:
        username = user.username
        if appbuilder.sm.del_register_user(user):
            logger.info('User {} deleted.'.format(username))

logger.info('Finished airflow ldap sync')
