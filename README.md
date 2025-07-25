# jjdiff
A TUI that can be used as a diff editor in the jujutsu vcs.

jjdiff will show all changes and allow you to navigate through them and
(partially) select them to be included.

jjdiff makes it easy to navigate the diff by having a 2 dimensional cursor that
can 'grow' and 'shrink'.

This cursor can operate on 3 levels:
- Change: select an entire change
- Hunk: select a group of edited lines in a file
- Line: select a single edited line in a file

## Keybindings
| Command | Key | Description |
| --- | --- | --- |
| `exit` | `escape`, `ctrl+c` or `ctrl+d` | Exit the diff editor with status code 1, causing the diff to not be applied. |
| `next_cursor` | `j`, `down` or `tab` | Select the next entry. |
| `prev_cursor` | `k`, `up` or `shift+tab` | Select the previous entry. |
| `shrink_cursor` | `l` or `right` | Shrink the cursor. So go from change to hunk and from hunk to line. If the cursor is on an unopened change it will open it first. |
| `grow_cursor` | `h` or `left` | Grow the cursor. So go from line to hunk and from hunk to change. If the cursor is on an opened change it will close it. |
| `select_cursor` | `space` | Mark everything selected by the cursor to be included. If everything is already marked it will exclude it instead. This will also select the next entry. |
| `confirm` | `enter` | Confirm the selected changes. | 
| `undo` | `u` | Undo the last command. Commands that only affect the UI state like changing the cursor and opening/closing changes are not included in this. |
| `redo` | `U` | Redo the last undone command. Commands that only affect the UI state like changing the cursor and opening/closing changes are not included in this. |
