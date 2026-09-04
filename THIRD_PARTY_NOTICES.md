# Third-party notices

Desktop Upgrade State Gate is an independent project. Its core Python action
uses the Python standard library. This file records tools and applications used
by the repository's optional examples and CI workflows; it does not imply that
their source or binaries are included in this repository's release.

## GitHub Actions used by workflows

The workflows reference the following actions by immutable commit SHA:

- [actions/checkout](https://github.com/actions/checkout) — MIT License
- [actions/setup-python](https://github.com/actions/setup-python) — MIT License
- [actions/upload-artifact](https://github.com/actions/upload-artifact) — MIT License

The actions are fetched by GitHub Actions when a workflow runs. Their source is
not copied into this repository.

## Playwright

The optional Beekeeper historical adapter declares
`@playwright/test` 1.44.0 as a separately installed dependency.

- Project: [Microsoft Playwright](https://github.com/microsoft/playwright)
- License: [Apache License 2.0](https://github.com/microsoft/playwright/blob/main/LICENSE)

Playwright and its `node_modules` tree are not included in this repository.

## Beekeeper Studio historical test target

The optional historical proof resolves and downloads explicitly selected
Beekeeper Studio release artifacts at workflow runtime. Beekeeper Studio source,
executables, plugins, icons and screenshots are not distributed as part of this
action.

- Project: [Beekeeper Studio](https://github.com/beekeeper-studio/beekeeper-studio)
- Community Edition license:
  [GPL-3.0-or-later](https://github.com/beekeeper-studio/beekeeper-studio/blob/master/LICENSE.md)
- Beekeeper Studio states that code under `src-commercial` is governed by a
  separate commercial license.

The historical proof is an independent compatibility experiment. It is not
affiliated with or endorsed by Beekeeper Studio.

## Distribution boundary

Do not add third-party application binaries, source code, plugins, icons,
screenshots or other brand assets to a release without a separate provenance,
license and trademark review. Keep runtime-downloaded artifacts hash-pinned and
outside uploaded evidence unless redistribution is expressly permitted.
