# built-in
from argparse import ArgumentParser

# app
from ..actions import get_python_env, attach_deps
from ..config import builders
from ..controllers import analize_conflict
from ..converters import CONVERTERS, InstalledConverter
from ..models import Requirement
from ..package_manager import PackageManager
from .base import BaseCommand


class DepsInstallCommand(BaseCommand):
    """Install project dependencies.

    https://dephell.readthedocs.io/en/latest/cmd-deps-install.html
    """
    @classmethod
    def get_parser(cls):
        parser = ArgumentParser(
            prog='dephell deps install',
            description=cls.__doc__,
        )
        builders.build_config(parser)
        builders.build_to(parser)
        builders.build_resolver(parser)
        builders.build_api(parser)
        builders.build_venv(parser)
        builders.build_output(parser)
        builders.build_other(parser)
        return parser

    def __call__(self) -> bool:
        loader_config = self.config.get('to') or self.config['from']
        self.logger.info('get dependencies', extra=dict(
            format=loader_config['format'],
            path=loader_config['path'],
        ))
        loader = CONVERTERS[loader_config['format']]
        resolver = loader.load_resolver(path=loader_config['path'])
        attach_deps(resolver=resolver, config=self.config, merge=False)

        # resolve
        self.logger.info('build dependencies graph...')
        resolved = resolver.resolve(silent=self.config['silent'])
        if not resolved:
            conflict = analize_conflict(resolver=resolver)
            self.logger.warning('conflict was found')
            print(conflict)
            return False

        # filter deps by envs
        resolver.apply_envs(set(self.config['envs']))

        # get executable
        python = get_python_env(config=self.config)
        self.logger.debug('choosen python', extra=dict(path=str(python.path)))

        # get installed packages
        installed_root = InstalledConverter().load(path=python.lib_path)
        installed = {dep.name: str(dep.constraint).strip('=') for dep in installed_root.dependencies}

        # plan what we will install and what we will remove
        install = []
        remove = []
        for req in Requirement.from_graph(graph=resolver.graph, lock=True):
            # not installed, install
            if req.name not in installed:
                install.append(req)
                continue
            # installed the same version, skip
            version = req.version.strip('=')
            if version == installed[req.name]:
                continue
            # installed old version, remove it and install new
            self.logger.debug('dependency will be updated', extra=dict(
                dependency=req.name,
                old=installed[req.name],
                new=version,
            ))
            remove.append(req)
            install.append(req)

        # remove
        manager = PackageManager(executable=python.path)
        if remove:
            self.logger.info('removing old packages...', extra=dict(
                executable=python.path,
                packages=len(remove),
            ))
            code = manager.remove(reqs=remove)
            if code != 0:
                return False

        # install
        if install:
            self.logger.info('installation...', extra=dict(
                executable=python.path,
                packages=len(install),
            ))
            code = manager.install(reqs=install)
            if code != 0:
                return False

        self.logger.info('installed')
        return True
