# Candidate execution prompt

Work only inside the assigned absolute workspace. Do not read the RAPTOR
repository, sibling benchmark runs, session-state files, internet sources or
any path outside the assigned workspace.

1. Read every file initially present in the assigned workspace.
2. Complete the role-specific task exactly as instructed.
3. Write only the requested artifact or authorized source/test changes.
4. Run bounded local verification when the role permits it.
5. Do not weaken fixtures, specifications or protected tests.
6. Do not install dependencies or use the network.
7. If the task cannot be completed, persist an explicit failure artifact
   explaining the precise blocker; never return success-shaped output.

The benchmark evaluator is hidden. Do not attempt to discover or infer its
location.
