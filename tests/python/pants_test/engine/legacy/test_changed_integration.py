# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open, touch
from pants_test.base_test import TestGenerator
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine
from pants_test.testutils.git_util import initialize_repo


def lines_to_set(str_or_list):
  if isinstance(str_or_list, list):
    return set(str_or_list)
  else:
    return set(x for x in str(str_or_list).split('\n') if x)


@contextmanager
def mutated_working_copy(files_to_mutate, to_append='\n '):
  """Given a list of files, append whitespace to each of them to trigger a git diff - then reset."""
  assert to_append, 'to_append may not be empty'

  for f in files_to_mutate:
    with open(f, 'ab') as fh:
      fh.write(to_append)
  try:
    yield
  finally:
    seek_point = len(to_append) * -1
    for f in files_to_mutate:
      with open(f, 'ab') as fh:
        fh.seek(seek_point, os.SEEK_END)
        fh.truncate()


@contextmanager
def create_isolated_git_repo():
  # Isolated Git Repo Structure:
  # worktree
  # |--README
  # |--pants.ini
  # |--3rdparty
  #    |--BUILD
  # |--src
  #    |--resources
  #       |--org/pantsbuild/resourceonly
  #          |--BUILD
  #          |--README.md
  #    |--java
  #       |--org/pantsbuild/helloworld
  #          |--BUILD
  #          |--helloworld.java
  #    |--python
  #       |--python_targets
  #          |--BUILD
  #          |--test_binary.py
  #          |--test_library.py
  #          |--test_unclaimed_src.py
  #       |--sources
  #          |--BUILD
  #          |--sources.py
  #          |--sources.txt
  # |--tests
  #    |--scala
  #       |--org/pantsbuild/cp-directories
  #          |--BUILD
  #          |--ClasspathDirectories.scala
  with temporary_dir(root_dir=get_buildroot()) as worktree:
    with safe_open(os.path.join(worktree, 'README'), 'w') as fp:
      fp.write('Just a test tree.')

    # Create an empty pants config file.
    touch(os.path.join(worktree, 'pants.ini'))

    # Copy .gitignore to new repo.
    shutil.copyfile('.gitignore', os.path.join(worktree, '.gitignore'))

    with initialize_repo(worktree=worktree, gitdir=os.path.join(worktree, '.git')) as git:
      # Resource File
      resource_file = os.path.join(worktree, 'src/resources/org/pantsbuild/resourceonly/README.md')
      with safe_open(resource_file, 'w') as fp:
        fp.write('Just resource.')

      resource_build_file = os.path.join(worktree, 'src/resources/org/pantsbuild/resourceonly/BUILD')
      with safe_open(resource_build_file, 'w') as fp:
        fp.write(dedent("""
        resources(
          name='resource',
          sources=['README.md'],
        )
        """))

      git.add(resource_file, resource_build_file)
      git.commit('Check in a resource target.')

      # Java Program
      src_file = os.path.join(worktree, 'src/java/org/pantsbuild/helloworld/helloworld.java')
      with safe_open(src_file, 'w') as fp:
        fp.write(dedent("""
        package org.pantsbuild.helloworld;

        class HelloWorld {
          public static void main(String[] args) {
            System.out.println("Hello, World!\n");
          }
        }
        """))

      src_build_file = os.path.join(worktree, 'src/java/org/pantsbuild/helloworld/BUILD')
      with safe_open(src_build_file, 'w') as fp:
        fp.write(dedent("""
        jvm_binary(
          dependencies=[
            '{}',
          ],
          source='helloworld.java',
          main='org.pantsbuild.helloworld.HelloWorld',
        )
        """.format('src/resources/org/pantsbuild/resourceonly:resource')))

      git.add(src_file, src_build_file)
      git.commit('hello world java program with a dependency on a resource file.')

      # Scala Program
      scala_src_dir = os.path.join(worktree, 'tests/scala/org/pantsbuild/cp-directories')
      safe_mkdir(os.path.dirname(scala_src_dir))
      shutil.copytree('testprojects/tests/scala/org/pantsbuild/testproject/cp-directories', scala_src_dir)
      git.add(scala_src_dir)
      git.commit('Check in a scala test target.')

      # Python library and binary
      python_src_dir = os.path.join(worktree, 'src/python/python_targets')
      safe_mkdir(os.path.dirname(python_src_dir))
      shutil.copytree('testprojects/src/python/python_targets', python_src_dir)
      git.add(python_src_dir)
      git.commit('Check in python targets.')

      # A `python_library` with `resources=['file.name']`.
      python_src_dir = os.path.join(worktree, 'src/python/sources')
      safe_mkdir(os.path.dirname(python_src_dir))
      shutil.copytree('testprojects/src/python/sources', python_src_dir)
      git.add(python_src_dir)
      git.commit('Check in a python library with resource dependency.')

      # Copy 3rdparty/BUILD.
      _3rdparty_build = os.path.join(worktree, '3rdparty/BUILD')
      safe_mkdir(os.path.dirname(_3rdparty_build))
      shutil.copyfile('3rdparty/BUILD', _3rdparty_build)
      git.add(_3rdparty_build)
      git.commit('Check in 3rdparty/BUILD.')

      with environment_as(PANTS_BUILDROOT_OVERRIDE=worktree):
        yield worktree


class ChangedIntegrationTest(PantsRunIntegrationTest, TestGenerator):

  TEST_MAPPING = {
    # A `jvm_binary` with `source='file.name'`.
    'src/java/org/pantsbuild/helloworld/helloworld.java': dict(
      none=['src/java/org/pantsbuild/helloworld:helloworld'],
      direct=['src/java/org/pantsbuild/helloworld:helloworld'],
      transitive=['src/java/org/pantsbuild/helloworld:helloworld']
    ),
    # A `python_binary` with `source='file.name'`.
    'src/python/python_targets/test_binary.py': dict(
      none=['src/python/python_targets:test'],
      direct=['src/python/python_targets:test'],
      transitive=['src/python/python_targets:test']
    ),
    # A `python_library` with `sources=['file.name']`.
    'src/python/python_targets/test_library.py': dict(
      none=['src/python/python_targets:test_library'],
      direct=['src/python/python_targets:test',
              'src/python/python_targets:test_library',
              'src/python/python_targets:test_library_direct_dependee'],
      transitive=['src/python/python_targets:test',
                  'src/python/python_targets:test_library',
                  'src/python/python_targets:test_library_direct_dependee',
                  'src/python/python_targets:test_library_transitive_dependee',
                  'src/python/python_targets:test_library_transitive_dependee_2',
                  'src/python/python_targets:test_library_transitive_dependee_3',
                  'src/python/python_targets:test_library_transitive_dependee_4']
    ),
    # A `resources` target with `sources=['file.name']` referenced by a `java_library` target.
    'src/resources/org/pantsbuild/resourceonly/README.md': dict(
      none=['src/resources/org/pantsbuild/resourceonly:resource'],
      direct=['src/java/org/pantsbuild/helloworld:helloworld',
              'src/resources/org/pantsbuild/resourceonly:resource'],
      transitive=['src/java/org/pantsbuild/helloworld:helloworld',
                  'src/resources/org/pantsbuild/resourceonly:resource'],
    ),
    # A `python_library` with `resources=['file.name']`.
    'src/python/sources/sources.txt': dict(
      none=['src/python/sources:sources'],
      direct=['src/python/sources:sources'],
      transitive=['src/python/sources:sources']
    ),
    # A `scala_library` with `sources=['file.name']`.
    'tests/scala/org/pantsbuild/cp-directories/ClasspathDirectories.scala': dict(
      none=['tests/scala/org/pantsbuild/cp-directories:cp-directories'],
      direct=['tests/scala/org/pantsbuild/cp-directories:cp-directories'],
      transitive=['tests/scala/org/pantsbuild/cp-directories:cp-directories']
    ),
    # An unclaimed source file.
    'src/python/python_targets/test_unclaimed_src.py': dict(
      none=[],
      direct=[],
      transitive=[]
    )
  }

  @classmethod
  def generate_tests(cls):
    """Generates tests on the class for better reporting granularity than an opaque for loop test."""
    def safe_filename(f):
      return f.replace('/', '_').replace('.', '_')

    for filename, dependee_mapping in cls.TEST_MAPPING.items():
      for dependee_type in dependee_mapping.keys():
        # N.B. The parameters here are used purely to close over the respective loop variables.
        def inner_integration_coverage_test(self, filename=filename, dependee_type=dependee_type):
          with create_isolated_git_repo() as worktree:
            # Mutate the working copy so we can do `--changed-parent=HEAD` deterministically.
            with mutated_working_copy([os.path.join(worktree, filename)]):
              stdout = self.assert_changed_new_equals_old(
                ['--changed-include-dependees={}'.format(dependee_type), '--changed-parent=HEAD'],
                test_list=True
              )

              self.assertEqual(
                lines_to_set(self.TEST_MAPPING[filename][dependee_type]),
                lines_to_set(stdout)
              )

        cls.add_test(
          'test_changed_coverage_{}_{}'.format(dependee_type, safe_filename(filename)),
          inner_integration_coverage_test
        )

  def assert_changed_new_equals_old(self, extra_args, success=True, test_list=False):
    args = ['-q', 'changed'] + extra_args
    changed_run = self.do_command(*args, success=success, enable_v2_engine=False)
    engine_changed_run = self.do_command(*args, success=success, enable_v2_engine=True)
    self.assertEqual(
      lines_to_set(changed_run.stdout_data), lines_to_set(engine_changed_run.stdout_data)
    )

    if test_list:
      # In the v2 engine, `--changed-*` options can alter the specs of any goal - test with `list`.
      list_args = ['-q', 'list'] + extra_args
      engine_list_run = self.do_command(*list_args, success=success, enable_v2_engine=True)
      self.assertEqual(
        lines_to_set(changed_run.stdout_data), lines_to_set(engine_list_run.stdout_data)
      )

    # If we get to here without asserting, we know all copies of stdout are identical - return one.
    return changed_run.stdout_data

  @ensure_engine
  def test_changed_options_scope_shadowing(self):
    """Tests that the `test-changed` scope overrides `changed` scope."""
    changed_src = 'src/python/python_targets/test_library.py'
    expected_target = self.TEST_MAPPING[changed_src]['none'][0]
    expected_set = {expected_target}
    not_expected_set = set(self.TEST_MAPPING[changed_src]['transitive']).difference(expected_set)

    with create_isolated_git_repo() as worktree:
      with mutated_working_copy([os.path.join(worktree, changed_src)]):
        pants_run = self.run_pants([
          '-ldebug',   # This ensures the changed target name shows up in the pants output.
          'test-changed',
          '--test-changed-changes-since=HEAD',
          '--test-changed-include-dependees=none',     # This option should be used.
          '--changed-include-dependees=transitive'     # This option should be stomped on.
        ])

      self.assert_success(pants_run)

      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

      for not_expected_item in not_expected_set:
        if expected_target.startswith(not_expected_item):
          continue  # Ignore subset matches.
        self.assertNotIn(not_expected_item, pants_run.stdout_data)

  @ensure_engine
  def test_changed_options_scope_positional(self):
    changed_src = 'src/python/python_targets/test_library.py'
    expected_set = set(self.TEST_MAPPING[changed_src]['transitive'])

    with create_isolated_git_repo() as worktree:
      with mutated_working_copy([os.path.join(worktree, changed_src)]):
        pants_run = self.run_pants([
          '-ldebug',   # This ensures the changed target names show up in the pants output.
          'test-changed',
          '--changes-since=HEAD',
          '--include-dependees=transitive'
        ])

      self.assert_success(pants_run)
      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

  @ensure_engine
  def test_test_changed_exclude_target(self):
    changed_src = 'src/python/python_targets/test_library.py'
    exclude_target_regexp = r'_[0-9]'
    excluded_set = {'src/python/python_targets:test_library_transitive_dependee_2',
                    'src/python/python_targets:test_library_transitive_dependee_3',
                    'src/python/python_targets:test_library_transitive_dependee_4'}
    expected_set = set(self.TEST_MAPPING[changed_src]['transitive']) - excluded_set

    with create_isolated_git_repo() as worktree:
      with mutated_working_copy([os.path.join(worktree, changed_src)]):
        pants_run = self.run_pants([
          '-ldebug',   # This ensures the changed target names show up in the pants output.
          '--exclude-target-regexp={}'.format(exclude_target_regexp),
          'test-changed',
          '--changes-since=HEAD',
          '--include-dependees=transitive'
        ])

      self.assert_success(pants_run)
      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

      for excluded_item in excluded_set:
        self.assertNotIn(excluded_item, pants_run.stdout_data)

  @ensure_engine
  def test_changed_changed_since_and_files(self):
    with create_isolated_git_repo():
      stdout = self.assert_changed_new_equals_old(['--changed-since=HEAD^^', '--files'])

      # The output should be the files added in the last 2 commits.
      self.assertEqual(
        lines_to_set(stdout),
        {'src/python/sources/BUILD',
         'src/python/sources/sources.py',
         'src/python/sources/sources.txt',
         '3rdparty/BUILD'}
      )

  @ensure_engine
  def test_changed_diffspec_and_files(self):
    with create_isolated_git_repo():
      git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD^^']).strip()
      stdout = self.assert_changed_new_equals_old(['--changed-diffspec={}'.format(git_sha), '--files'])

      # The output should be the files added in the last 2 commits.
      self.assertEqual(
        lines_to_set(stdout),
        {'src/python/python_targets/BUILD',
         'src/python/python_targets/test_binary.py',
         'src/python/python_targets/test_library.py',
         'src/python/python_targets/test_unclaimed_src.py'}
      )

  # Following 4 tests do not run in isolated repo because they don't mutate working copy.
  def test_changed(self):
    self.assert_changed_new_equals_old([])

  def test_changed_with_changes_since(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^'])

  def test_changed_with_changes_since_direct(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^', '--include-dependees=direct'])

  def test_changed_with_changes_since_transitive(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^', '--include-dependees=transitive'])


ChangedIntegrationTest.generate_tests()
