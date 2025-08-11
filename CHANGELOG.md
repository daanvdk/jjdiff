# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.3.0]: https://github.com/daanvdk/jjdiff/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/daanvdk/jjdiff/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/daanvdk/jjdiff/releases/tag/v0.1.0

