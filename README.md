\# ForumBot Pro



This repository contains the ForumBot Pro application.



\## Upload threading architecture

The upload pipeline now relies exclusively on Qt threading primitives:

* `UploadWorker` continues to run inside its own `QThread` but delegates host
  uploads to a dedicated `QThreadPool`.  Each host is processed by a
  `QRunnable`, ensuring that network operations execute in Qt-managed threads
  and progress is forwarded back to the UI through Qt signals.
* Completion for each batch is coordinated through an internal queue, keeping
  the worker thread responsive to cancellation and pause signals while
  consolidating results from the runnables.
* Retry requests are dispatched via a single-threaded Qt pool so that follow-up
  uploads never block the GUI thread and reuse the same signal-driven
  orchestration logic as the initial batch.

This design removes the previous `ThreadPoolExecutor` usage and avoids mixing
Python-native threads with Qt threads, simplifying cancellation and restart
behaviour.

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

