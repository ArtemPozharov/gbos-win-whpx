# gbos-win-whpx

## Model routing (to save usage)
Claude cannot change the session model itself; it flags switches in one line instead.
- Default: implementation work runs in a fresh session on Sonnet, using the active plan
  file as handoff (`C:\Users\smets\.claude\plans\3-questions-surfaceflinger-delightful-balloon.md`).
  Update the plan file with new findings at each checkpoint so a new session can resume.
- If the session is on Opus and the next task is mechanical (builds, image assembly,
  scripted edits, test boots), say so and suggest `/model sonnet` or a fresh Sonnet session.
- If the same problem has failed twice on Sonnet, or the task is analysis-heavy
  (SurfaceFlinger/EGL/SELinux/linker failures, design choices), suggest `/model opus`
  in the same session (keeps context; first turn after a switch costs extra).
- Noisy output (Mesa/meson builds, serial/logcat logs): filter in the command, or delegate
  to an Agent with `model: "sonnet"` that returns a short summary + relevant lines only.
