cd ~/syndicate-prod/logs
tail -c 40000000 refresh-worker.log.1 | cat - refresh-worker.log | grep -a "BOARD_BUILD_TIMING\|BUILD_SPAN_EXIT stage=layer2_shortlist_build\|DEFERRED_BOARD" | awk -v s="$1" '$1 >= s' | cut -c1-150
