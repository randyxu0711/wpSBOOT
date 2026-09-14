#!/bin/sh
# Fake aligner for tests. Mode from FAKE_<NAME> = ok | fail | empty | hang | env
mode=$(printenv "FAKE_$(basename "$0" | tr a-z_ A-Z_)")
echo "fake $(basename "$0") running" >&2
case "$mode" in
  fail) exit 3 ;;
  env) env >&2 ;;
  hang) sleep 60 & wait ;;
esac
out=""
for arg in "$@"; do
  case "$arg" in
    -out) next=1 ;;
    -outfile=*) out="${arg#-outfile=}" ;;
    *) [ -n "$next" ] && out="$arg" && next="" ;;
  esac
done
[ "$mode" = empty ] && exit 0
if [ -z "$out" ]; then cat input.fasta; else cp input.fasta "$out"; fi
