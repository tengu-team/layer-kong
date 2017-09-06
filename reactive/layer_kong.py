from charmhelpers.core import unitdata
from charmhelpers.core.hookenv import status_set, log, config, open_port, close_port
from charmhelpers.core.host import service_restart, service_start
from charmhelpers.core.templating import render
from charms.reactive import when, when_not, set_state, remove_state
from charms import layer

import shutil
import subprocess

@when_not('cassandra.available')
def cassandra_removed():
    remove_state('kong.connected')
    status_set('blocked', 'Waiting for a connection with Cassandra.')

@when('config.changed', 'kong.started')
def config_changed():
    conf = config()
    db = unitdata.kv()
    changed = False
    if conf.get('proxy_port') != db.get('proxy_port'):
        changed = True
        close_port(db.get('proxy_port'))
        db.set('proxy_port', conf.get('proxy_port'))
    if conf.get('admin_port') != db.get('admin_port'):
        changed = True
        close_port(db.get('admin_port'))
        db.set('admin_port', conf.get('admin_port'))
    
    if changed:
        status_set('maintenance', '(Updating) Adjusting settings')
        context = {
            'host': db.get('host'),
            'proxy_port': db.get('proxy_port'),
            'admin_port': db.get('admin_port'),
            'db_update_propagation': db.get('db_update_propagation'),
            'cass_contact_points': db.get('cass_cp'),
            'cass_port': db.get('cass_port'),
            'cass_username': db.get('cass_username'),
            'cass_password': db.get('cass_password'),
        }
        render('kong.conf', '/etc/kong/kong.conf', context)
        subprocess.call(['kong', 'restart'])
        open_port(db.get('proxy_port'))
        open_port(db.get('admin_port'))
        set_state('kong.started')
        status_set('active', '(Ready) Kong running.')


@when('cassandra.available', 'kong.installed')
@when_not('kong.connected')
def cassandra_attached(cassandra):
    status_set('maintenance', 'Configuring connection with Cassandra.')
    db = unitdata.kv()
    cass_cp = []
    for cass_conf in cassandra.get_configuration():
        print(cass_conf["native_transport_port"])
        if cass_conf["native_transport_port"]:
            cass_cp.append(cass_conf["host"])
            db.set('cass_port', cass_conf["native_transport_port"])
            db.set('cass_username', cass_conf["username"])
            db.set('cass_password', cass_conf["password"])
        else:
            return
    db.set('cass_cp', ','.join(cass_cp))
    if len(cass_cp) > 1:
        db.set('db_update_propagation', len(cass_cp))
    else:
        db.set('db_update_propagation', 0)
    conf = config()
    db.set('host', '0.0.0.0')
    db.set('proxy_port', conf.get('proxy_port'))
    db.set('admin_port', conf.get('admin_port'))
    context = {
        'host': db.get('host'),
        'proxy_port': db.get('proxy_port'),
        'admin_port': db.get('admin_port'),
        'db_update_propagation': db.get('db_update_propagation'),
        'cass_contact_points': db.get('cass_cp'),
        'cass_port': db.get('cass_port'),
        'cass_username': db.get('cass_username'),
        'cass_password': db.get('cass_password'),
    }
    render('kong.conf', '/etc/kong/kong.conf', context)
    set_state('kong.connected')

@when('apt.installed.openssl', 'apt.installed.libpcre3', 'apt.installed.procps', 'apt.installed.perl')
@when_not('kong.installed', 'kong.started')
def install_kong():
    options = layer.options()
    deb = options['kong']['kong_deb']
    status_set('maintenance', 'Installing Kong from {}.'.format(deb))
    subprocess.call(['wget', '-O', 'kong.deb', deb])
    subprocess.call(['sudo', 'dpkg', '-i', 'kong.deb'])
    set_state('kong.installed')

@when('kong.installed', 'kong.connected')
@when_not('kong.started')
def start_kong():
    conf = config()
    subprocess.call(['kong', 'migrations', 'up'])
    subprocess.call(['kong', 'start'])
    open_port(conf.get('proxy_port'))
    open_port(conf.get('admin_port'))
    set_state('kong.started')
    status_set('active', '(Ready) Kong running.')

@when('proxy-endpoint.available', 'kong.started')
def configure_proxy_http(http):
    log('Client connected to the proxy http endpoint.')

    db = unitdata.kv()
    http.configure(
        hostname=unit_private_ip(),
        private_address=unit_private_ip(),
        port=db.get('proxy_port'))

@when('admin-api.available', 'kong.started')
def configure_admin_http(http):
    log('Client connected to the admin http endpoint.')

    db = unitdata.kv() 
    http.configure(
        hostname=unit_private_ip(),
        private_address=unit_private_ip(),
        port=db.get('admin_port'))
