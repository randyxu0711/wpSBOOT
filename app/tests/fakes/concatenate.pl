# Fake concatenate.pl for tests: prints the same report format and writes a dummy PHYLIP file.
my @files; my $out; my $mode = 'aln';
for (@ARGV) {
  if ($_ eq '--aln') { $mode = 'aln'; next } if ($_ eq '--out') { $mode = 'out'; next }
  next if /^--/;
  if ($mode eq 'aln') { push @files, $_ } else { $out = $_ }
}
@files = reverse @files;
print "\nHow to concatenate:\n\torder: random\n\talignments:";
print "\n\t\t$_" for @files;
print "\n\toutput: $out \n";
open(my $fh, '>', $out) or die; print $fh "phylip\n"; close $fh;
