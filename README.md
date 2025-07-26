\# ForumBot Pro



This repository contains the ForumBot Pro application.



\## Auto-Process Mode



A new \*\*Auto-Process Selected\*\* action is available in the Process Threads view.

Use the toolbar button or right click context menu to queue threads for

automatic processing. Each selected thread becomes a job stored in

`data/jobs.json` and processed sequentially. Jobs survive application restarts.



To start from code:

```python

from gui.main\_window import ForumBotGUI



\# gui is an instance of ForumBotGUI

thread\_ids = \[123, 456]

gui.start\_auto\_process(thread\_ids)

