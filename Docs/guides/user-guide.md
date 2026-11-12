# ServerPulse User Guide

ServerPulse shows how busy your computers are. It shows CPU use, memory use,
and the programs running on each machine, all in one web dashboard.

This guide is for people who sign in and look at the dashboard. For setting up
the server and registering machines, see the [Admin Guide](admin-guide.md).

## Key terms

| Term | Meaning |
| --- | --- |
| **Server (backend)** | The ServerPulse service that stores data and serves the dashboard. |
| **Dashboard** | The web page you use in a browser. |
| **Machine** | A computer being monitored: a Windows PC, a Linux computer, a WSL Linux system, or another server. |
| **Collector** | A small background program that runs on each machine. It measures the machine and sends the results to the server. See [What the collector does](#what-the-collector-does). |
| **Collector token** | A secret code that identifies one machine to the server. It is shown once when the machine is registered. |
| **Snapshot** | One set of measurements (CPU, memory, processes) sent by a collector. |

## Signing in

1. Open the dashboard in your browser (for example `http://localhost:5173`).
2. Enter your username and password, then sign in.
3. To create a new account, use the registration option on the sign-in page.

## What the collector does

The collector is the only part that runs on the monitored machine. It has one job:

1. Every few seconds (10 by default), it measures the machine's CPU, memory, and running programs.
2. It sends that measurement to the server.
3. If the server cannot be reached, it keeps the latest measurement and retries. It does not send an unlimited backlog.

The collector does not change anything on the machine. It does not stop or restart programs,
and it does not read passwords, environment variables, or command lines.

Important points:

- A machine only shows data after its collector is installed, started, and connected.
  Registering a machine in the dashboard is not enough.
- Each collector has its own token. It can only send data for its own machine.
- Each user can register only one **localhost** (local) machine, and each WSL distribution only once. A duplicate (same local machine, same WSL distribution, or same name) is rejected with "This machine is already registered".
- A machine is marked **offline** if no new measurement arrives for about 60 seconds.
  The last measurement stays visible with its time, so you can see when it was taken.

## Using the Machines page

Open **Machines** in the dashboard.

- **Machine list (left side):** every registered machine, its platform, deployment type,
  and whether it is connected. Use the search and filters to narrow the list.
- **Latest resources:** current CPU and memory use, available memory, and process counts.
  Long-running and zombie process counts appear here.
- **Resource history:** a chart of recent CPU and memory use (the last 24 hours).
- **Processes:** a table of running programs on the selected machine. You can:
  - search by name,
  - sort by CPU, memory, runtime, or name,
  - show only **long-running** processes,
  - on Linux, show only **zombie** processes.
- **Process history:** select a process to see how its CPU and memory changed over time.

### Reading the numbers

- **CPU** is a percentage of the whole machine (0–100%).
- **Memory used** is total memory minus available memory.
- **Process memory** is the memory each program uses. Programs can share memory,
  so adding up all process values will not equal the machine's total memory use.
- **Long-running** means a process has been running longer than the machine's threshold
  (one hour by default). It is only a label for information. It does not mean the program is stuck.
- **Zombie** (Linux only) is a finished program that its parent has not cleaned up yet.
  Zombies are shown as not applicable on Windows.
- **Partial visibility:** if the collector cannot read some programs (for example, system programs
  that need administrator rights), those rows are still shown, and a count of hidden items is displayed.
- **Empty state:** a machine with no data yet shows "no data", not zero usage.

## Common questions

**The machine says offline.**
The collector is not running, cannot reach the server, or the machine is asleep.
Ask your administrator to check the collector on that machine.

**I see "no data" for a new machine.**
The collector has not sent a measurement yet. Wait a few seconds, then refresh.
If it still shows no data, ask your administrator to check the collector setup.

**Why does a process show no CPU value?**
The first measurement of a process has no earlier value to compare with, so its CPU is unknown
until the next sample. Unknown is not the same as zero.

**Why do WSL numbers differ from Windows numbers?**
A WSL machine reports the resources of its own Linux environment, not the whole Windows computer.

**Why can't I change settings?**
Only administrators can enable or disable machines of other users, or view every machine. Owners can change thresholds, enable or disable their own machines, and rotate their own collector tokens. When an administrator changes an owner's machine, the owner gets a notification in the Machines page explaining the change and the next step.
Ask an administrator. You can register your own machines and see their data.

**How do I get alerts for my machine?**
Open the machine's **Settings** tab and use **Alert rules**. Give each rule a name, pick a
metric (CPU, memory, long-running processes, zombie processes, or a named process's CPU,
memory, or count), set a threshold, and set how many minutes the breach must last before it
fires. You can add several rules for the same metric, such as a warning and a critical one.
Use **Edit** to change a rule, the **Enabled** switch to pause it, and **Delete** to remove
it. Deleting a rule also removes its alert history. Each machine can have up to 50 rules.
When a rule fires or resolves, you get a notification. Open the bell in the top bar to read
it, dismiss it, or mark all as read. The bell shows a badge for unread notifications.
Zombie rules are available only for Linux machines. Process rules match the process name
without regard to case. Process CPU is summed across all matching processes, so it can
exceed 100% on multi-core machines.

**How do I start the collector for a machine on this server?**
Select a machine with deployment type `localhost` and use **Start collector** in its detail view.
The backend starts the collector process for you. Starting issues a new credential, so any other
collector still using the old credential for that machine stops being accepted.

**Why can't I see a machine someone else registered?**
You only see the machines you registered. Administrators can see every machine.

## Current limits

ServerPulse currently monitors CPU, memory, processes, and the service inventory (Windows
Services and systemd services) with their observed state. Service state-change history,
alerts, log search, and reports are planned but not yet available.
