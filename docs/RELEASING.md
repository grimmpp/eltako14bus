# Versioning and release process

This project uses a version format compatible with Semantic Versioning:

```text
MAJOR.MINOR.PATCH
```

The project is currently in the `0.x` series. Existing releases have used
patch-style increments (`0.0.81`, `0.0.82`, ...), so the next compatible
release after `0.0.82` is `1.0.0`.

## Choosing the version number

- **Patch**: bug fixes, documentation, tests, and backward-compatible metadata
  or API additions. Example: `1.0.0`.
- **Minor**: a larger backward-compatible feature release when the project
  adopts a more conventional `0.x` versioning scheme.
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

Run the tests and static checks:

```sh
python -m pytest -q
python -m compileall -q eltakobus tests eltakotool.py
git diff --check
```

The repository's GitHub Actions release workflow currently installs
`requirements.txt`, runs `pytest tests`, builds the package, and publishes it
to PyPI. Run the same checks locally before creating a release.

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
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
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
