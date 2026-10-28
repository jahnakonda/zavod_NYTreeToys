@echo off
rem Плановый запуск nytoys-researcher (фоновый, без интеракции).
rem Задание на русском — в research\cron-task.md (UTF-8), чтобы обойти кодировки cmd.
cd /d K:\FABRICA\work\own\zavod_NYTreeToys
echo === START %date% %time% === >> ..\..\tmp\researcher-scheduled.log
claude -p "Read the task file research/cron-task.md and execute it fully and autonomously. This is an unattended scheduled run: do not ask questions, work to completion and write a final report (in Russian) to stdout. Reply format: see the task file." >> ..\..\tmp\researcher-scheduled.log 2>&1
echo === END %date% %time% === >> ..\..\tmp\researcher-scheduled.log