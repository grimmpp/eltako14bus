# Versioning and release process

This project uses a version format compatible with Semantic Versioning:

```text
MAJOR.MINOR.PATCH
```

The project is now in the `1.x` series. The `1.0.0` release established the
current public API and metadata model; subsequent compatible fixes use the
patch component.

The current release is `1.0.1`, which adds the requested Eltako A5 and ESP3
VLD EEP decoders while preserving the existing ESP2 API.

## Choosing the version number

- **Patch**: bug fixes, documentation, tests, and backward-compatible metadata
  or API additions. Example: `1.0.1`.
- **Minor**: a larger backward-compatible feature release, for example `1.1.0`.
- **Major**: an intentional breaking API or behavior change.

During the `0.x` phase, any breaking change must be called out explicitly in
`CHANGES.md`, even when the numeric increment follows the repository's current
patch-style convention.

## Files to update

For every release:

1. Update `version` in `setup.py`.
2. Add a new, dated or clearly numbered section at the top of `CHANGES.md`.
3. Document compatibility concerns and migration steps for breaking changes.
4. Update user/developer documentation when public behavior or commands
   change.
5. Add or update tests for the change.

The package currently has no separate `__version__` constant, so `setup.py` is
the packaging source of truth. If a runtime version is added later, it must be
kept synchronized or derived from one canonical source.

## Local verification

Create an isolated environment and install the dependencies needed by the
transport and test suite:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[serial,coap,eltakotool]'
python -m pip install pytest build wheel
```

The CoAP extra requires a current `aiocoap` release. The project declares
`aiocoap >= 0.4.17, < 1`; the obsolete `0.4a1` release is incompatible with
modern Python because it uses the removed `asyncio.coroutine` API.

Run the tests and static checks:

```sh
python -m pytest -q
python -m compileall -q eltakobus tests eltakotool.py
git diff --check
```

The repository has two GitHub Actions workflows. `ci.yml` runs on pushes and
pull requests on Python 3.10 through 3.14. `release.yml` runs only after a
GitHub Release is published, repeats the tests, compiles the sources, builds
the wheel and source archive, validates them with `twine check`, verifies a
wheel installation, and only then publishes to PyPI. Both workflows install
the package extras directly, so CI exercises the same dependency declaration
used by consumers instead of the legacy `requirements.txt` file.

Build and inspect the distribution artifacts locally:

```sh
python -m build
python -m twine check dist/*
```

Do not publish from a dirty working tree. Confirm that the generated wheel and
source archive contain the intended version and files.

## Git and GitHub release

The current automated publishing workflow is triggered by a published GitHub
Release:

1. Commit the version, changelog, documentation, and tests.
2. Review the diff and run the local verification commands.
3. Create and push an annotated tag matching the package version, for example:

   ```sh
   git tag -a v1.0.1 -m "Release v1.0.1"
   git push origin v1.0.1
   ```

4. Create a GitHub Release for that tag and paste the corresponding
   `CHANGES.md` section into the release description.
5. Publish the GitHub Release. The `release.yml` workflow then builds the
   package and uploads it to PyPI using the repository's `PYPI_TOKEN` secret.
6. Verify the published version from a clean environment:

   ```sh
   python -m pip install --upgrade eltakobus
   python -m pip show eltakobus
   ```

The tag, GitHub Release, `setup.py`, and PyPI version must all agree. PyPI does
not allow replacing an already-uploaded version, so resolve version mistakes
by creating a new patch release rather than reusing the number.

## Release checklist

- [ ] Version incremented in `setup.py`.
- [ ] `CHANGES.md` updated at the top.
- [ ] Public API and compatibility impact documented.
- [ ] Tests pass with the supported dependencies.
- [ ] Compilation and `git diff --check` pass.
- [ ] Build artifacts pass `twine check`.
- [ ] Working tree contains only intentional release changes.
- [ ] Annotated version tag pushed.
- [ ] GitHub Release published for the tag.
- [ ] PyPI publication workflow succeeded.
- [ ] Clean-environment installation verified.
