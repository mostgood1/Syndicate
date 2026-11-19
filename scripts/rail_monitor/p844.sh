# #844 sampler (handed over 11-19 by lane ncaab-total-overprojection). Read-only; appends one JSON line per sport.
# usage: wsl -- nice -n 19 bash /mnt/c/tmp/railmon/p844.sh <date YYYY-MM-DD>
D="$1"
cd ~/Syndicate || exit 1
for S in ncaab nba; do
  nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/p844_grid_sample.py "$S" "$D" >> "/mnt/c/tmp/railmon/p844_${D}.jsonl" 2>> "/mnt/c/tmp/railmon/p844_${D}.err"
done
tail -2 "/mnt/c/tmp/railmon/p844_${D}.jsonl"
