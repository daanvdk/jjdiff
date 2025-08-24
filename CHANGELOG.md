# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Added a configuration file at `$XDG_CONFIG_HOME/jjdiff/config.toml`.
- Added a deprioritize feature where you can specify a list of gitignore like patterns to deprioritze in `diff.deprioritize`. These files have the following behaviour:
  - changes on these files appear after changes on regular files.
  - `jjdiff --print` does not show the contents of the change.
- Added a small change summary of addition and deletion count to file changes.
- Added a `format.tab_width` setting to configure as how many spaces a tab character shows (default 4).

### Fixed
- Fixed a bug where files containing tab characters would have messed up line wrapping.
- Fixed a bug where applying a rename that introduced a new parent directory would crash.
- Fixed a bug where the file mode of new files would not get used.

## [0.3.0] - 2025-08-11
### Fixed
- Fixed a bug where hunk cursors would freeze when navigating to the next file.

### Changed
- Scrollbar is not shown when content fits
- Changed text color of omitted lines

## [0.2.0] - 2025-07-27
### Added
- A `--print` flag that causes the command to just print the diff instead of opening an editor.

### Changed
- File changes now show a check if they are fully selected, a minus sign if they are partially selected, and a cross if they are not selected at all.
- Renames and mode changes now show a diff when opened.

### Fixed
- Fixed visual issues around line wrapping.

## [0.1.0] - 2025-07-25
### Added
- Initial version of the application.

[Unreleased]: https://github.com/daanvdk/jjdiff/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/daanvdk/jjdiff/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/daanvdk/jjdiff/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/daanvdk/jjdiff/releases/tag/v0.1.0

