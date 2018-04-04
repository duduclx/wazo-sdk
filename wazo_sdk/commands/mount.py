# Copyright 2018 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0+


from cliff.command import Command


class Mount(Command):

    def get_parser(self, *args, **kwargs):
        parser = super().get_parser(*args, **kwargs)
        parser.add_argument('--list', action='store_true', help='list mounted repositories')
        parser.add_argument('repos', nargs='*', default=[], help='a list repos to mount')
        return parser

    def take_action(self, parsed_args):
        for repo in parsed_args.repos:
            self.mounter.mount(repo)

        if parsed_args.list:
            mounted_repos = self.mounter.list_()
            for repo in mounted_repos:
                self.app.LOG.info(repo)


class Umount(Command):

    def get_parser(self, *args, **kwargs):
        parser = super().get_parser(*args, **kwargs)
        parser.add_argument('repos', nargs='*', default=[], help='a list repos to unmount')
        return parser

    def take_action(self, parsed_args):
        repos = parsed_args.repos or self.mounter.list_()
        for repo in repos:
            self.mounter.umount(repo)