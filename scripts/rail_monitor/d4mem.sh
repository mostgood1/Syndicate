cd ~/syndicate-prod/logs
uptime
ps -eo pid,ni,pcpu,etimes,rss,args --sort=-pcpu | head -6 | cut -c1-140
grep -a '\[board_process\]\|RECYCLE_EXIT\|MEMORY_GUARD_ABORT' refresh-worker.log | awk -v s="$1" '$1 >= s' | cut -c1-200
cd ~/Syndicate && git reflog -1 --date=iso | cat
