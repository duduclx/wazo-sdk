# Copyright 2018 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0+

import psutil
import os
import sh
import signal
import subprocess

REPO_PREFIX = ['', 'wazo-', 'xivo-']


def _list_processes():
    for pid in psutil.pids():
        try:
            with open(os.path.join('/proc', str(pid), 'cmdline', ), 'r') as f:
                yield pid, f.read()[:-1]
        except IOError:
            # Process already completed
            pass


class Mounter:

    def __init__(self, logger, config):
        self.logger = logger
        self._config = config
        self._hostname = config.hostname
        self._local_dir = config.local_source
        self._remote_dir = config.remote_source

    def list_(self):
        return [repo for _, repo in self._list_sync()]

    def _list_sync(self):
        for pid, cmd in _list_processes():
            if 'lsyncd' not in cmd:
                continue

            yield pid, cmd.split('/')[-1]

    def _is_mounted(self, repo_name):
        for pid, repo in self._list_sync():
            if repo == repo_name:
                return True
        return False

    def mount(self, repo_name):
        if not self._hostname:
            raise Exception('The remote hostname is required to mount directories')

        if not self._local_dir:
            raise Exception('The local source directory is required to mount directories')

        local_repo_name = self._find_local_repo_name(repo_name)
        real_repo_name = self._config.get_project_name(repo_name)

        if self._is_mounted(real_repo_name):
            self.logger.debug('%s is already mounted', real_repo_name)
        else:
            self._start_sync(local_repo_name, real_repo_name)

        repo_config = self._config.get_project(real_repo_name)
        self._apply_mount(real_repo_name, repo_config)

    def umount(self, repo_name):
        if not self._local_dir:
            raise Exception('The local source directory is required to mount directories')

        real_repo_name = self._config.get_project_name(repo_name)

        repo_config = self._config.get_project(real_repo_name)
        self._unapply_mount(real_repo_name, repo_config)

        if not self._is_mounted(real_repo_name):
            self.logger.debug('%s is not mounted', real_repo_name)
        else:
            self._stop_sync(real_repo_name)

    def _apply_mount(self, repo_name, config):
        if not config:
            return

        wazo = sh.ssh.bake(self._hostname)

        if config.get('python2'):
            self._mount_python2(wazo, repo_name)
        if config.get('python3'):
            self._mount_python3(wazo, repo_name)
        binds = config.get('bind')
        if binds:
            self._bind_files(wazo, repo_name, binds)

    def _unapply_mount(self, repo_name, config):
        if not config:
            return

        wazo = sh.ssh.bake(self._hostname)

        if config.get('python2'):
            self._umount_python2(wazo, repo_name)
        if config.get('python3'):
            self._umount_python3(wazo, repo_name)
        binds = config.get('bind')
        if binds:
            self._remove_bind_files(wazo, repo_name, binds)
        clean = config.get('clean')
        if clean:
            self._clean_files(wazo, clean)

    def _bind_files(self, ssh, repo_name, binds):
        mount_output = ssh('mount').strip().split('\n')
        mounted = []
        for line in mount_output:
            cols = line.split(' ')
            mounted.append(cols[2])

        self.logger.debug('mounted: %s', mounted)

        for source, dest in binds.items():
            if dest in mounted:
                self.logger.debug('%s is already mounted...', dest)
                continue
            src_path = os.path.join(self._remote_dir, repo_name, source)
            self._wait_for_file(ssh, src_path)
            cmd = ['mount', '--bind', src_path, dest]
            self.logger.debug(ssh(' '.join(cmd)))

    def _clean_files(self, ssh, files):
        ssh('rm -rf {}'.format(' '.join(files)))

    def _remove_bind_files(self, ssh, repo_name, binds):
        mount_output = ssh('mount').strip().split('\n')
        mounted = []
        for line in mount_output:
            cols = line.split(' ')
            mounted.append(cols[2])

        self.logger.debug('mounted: %s', mounted)

        for source, dest in binds.items():
            if dest not in mounted:
                continue

            cmd = ['umount', dest]
            self.logger.debug(ssh(' '.join(cmd)))

    def _mount_python2(self, ssh, repo_name):
        setup_path = os.path.join(self._remote_dir, repo_name, 'setup.py')
        self._wait_for_file(ssh, setup_path)

        repo_dir = os.path.join(self._remote_dir, repo_name)
        cmd = ['cd', repo_dir, ';', 'python2', 'setup.py', 'develop']
        self.logger.debug(ssh(' '.join(cmd)))

    def _mount_python3(self, ssh, repo_name):
        setup_path = os.path.join(self._remote_dir, repo_name, 'setup.py')
        self._wait_for_file(ssh, setup_path)

        repo_dir = os.path.join(self._remote_dir, repo_name)
        cmd = ['cd', repo_dir, ';', 'python3', 'setup.py', 'develop']
        self.logger.debug(ssh(' '.join(cmd)))

    def _umount_python2(self, ssh, repo_name):
        repo_dir = os.path.join(self._remote_dir, repo_name)
        cmd = ['cd', repo_dir, ';', 'python2', 'setup.py', 'develop', '--uninstall']
        self.logger.debug(ssh(' '.join(cmd)))

    def _umount_python3(self, ssh, repo_name):
        repo_dir = os.path.join(self._remote_dir, repo_name)
        cmd = ['cd', repo_dir, ';', 'python3', 'setup.py', 'develop', '--uninstall']
        self.logger.debug(ssh(' '.join(cmd)))

    def _wait_for_file(self, ssh, filename):
        ssh('while [ ! -e {} ]; do sleep 0.2; done'.format(filename))

    def _start_sync(self, local_repo_name, real_repo_name):
        local_path = os.path.join(self._local_dir, local_repo_name)
        remote_path = os.path.join(self._remote_dir, real_repo_name)

        lsync_command = [
            'lsyncd',
            '-delay', '1',
            '-rsyncssh', local_path, self._hostname, remote_path,
        ]

        self.logger.debug('%s', ' '.join(lsync_command))
        ret = subprocess.call(lsync_command)
        if ret:
            self.logger.info('%s failed %s', ' '.join(lsync_command), ret)

    def _stop_sync(self, repo_name):
        for pid, repo in self._list_sync():
            if repo != repo_name:
                continue
            os.kill(pid, signal.SIGTERM)

    def _find_local_repo_name(self, repo_name):
        for prefix in REPO_PREFIX:
            basename = '{}{}'.format(prefix, repo_name)
            path = os.path.join(self._local_dir, basename)
            if os.path.exists(path):
                return basename

        raise Exception('No such repo {}'.format(repo_name))