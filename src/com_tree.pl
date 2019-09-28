#!/usr/bin/env perl

my $argc;   # Declare variable $argc. This represents the number of commandline parameters entered.
my @score;
$trees_file="trees_cmp.ph";

$argc = @ARGV; # Save the number of commandline parameters.
if (@ARGV==0)
{
  usage();  # Call subroutine usage()
}

parse_show_command();

$pro_name = get_prefix_name($input_files[1]);

compare_tree_by_Phylip();
compare_tree_by_tcoffee();

sub compare_tree_by_Phylip
{
	unlink ("outfile");
	print "Run treedist.....";
	$con_c="tmp.txt";
	open (F, ">$con_c");
	print F "$trees_file\nD\n2\nP\nF\nY\n";
	close (F);
	`treedist < $con_c`;
	if ( -e "outfile"){ print "[OK]\n";}
	else { print "[FAILED]\n";exit (EXIT_FAILURE);}
	system("cat outfile");
	unlink ($trees_file);
	unlink ($con_c);
	unlink ("outfile");
}

sub usage
  {
    print "com_tree.pl -dis_mod <bra|sys> -a <0|1> -p <0|1> -i <tree_file1> <tree_file2> ...";
    print "\n\t-p: plot tree or not (default : 0)";
    print "\n\t-i: input tree files";
    print "\n\t-dis_mod: Mode of comparing tree in Phylip (default: sys)";
    print "\n\t\tbra: Branch Score Distance";
    print "\n\t\tsys: The symmetric Difference does not consider the branch lengths, only the tree topologies.";
    print "\n\t-a: compare all pairs (default : 0), set 0 will just compare other trees to first tree(like an reference tree)\n";
    exit (EXIT_FAILURE);
  }

sub parse_show_command
{
	foreach $arg (@ARGV){$command.="$arg ";}
	print "CLINE: $command\n";	
	print "[Parameters]\n";

	$dis_mod="sys";
	if(($command=~/\-dis_mod (\S+)/))
	{
		$dis_mod=$1;
	}
	print "\t-dis_mod=$dis_mod\n";

	$all=0;
	if(($command=~/\-a (\S+)/))
	{
		$all=$1;
		print "\t-a=$all\n";
	}

	$plot=0;
	if(($command=~/\-p (\S+)/))
	{
		$plot=$1;
		print "\t-p=$plot\n";
	}

	if($command=~/\-i (.+)/)
	{
		unlink ($trees_file);
		print "\tInput Files:\n";
		@input_files=split(/ /,$1);
		$count=1;
		foreach $file (@input_files)
		{
			print "\t\tTree$count = $file\n";
			if($plot)
			{
				plot_tree($file);
			}
			`cat $file >> $trees_file`;
			`echo >> $trees_file`;
			$count++;
		}
	}
	else
	{
		usage();	
	}
}

sub plot_tree
{
	$font_file="/home/cjiaming/program/phylip-3.68/fontfile";
	($input_name) = @_;
	$output_name = $input_name;
	$output_name =~ s/ph$/ps/g;
	$con_c="tmp.txt";	
	open (F, ">$con_c");
	if ( -e "font_file")
	{
		print F "$input_name\nV\nN\nY\n";
	}
	else
	{
 		print F "$input_name\n$font_file\nV\nN\nY\n";
	}
	close (F);
	`drawtree < $con_c`;
	if ( -e "plotfile"){ print "\t ps = $output_name\n";}
	else { print "[FAILED]\n";exit (EXIT_FAILURE);}
	`mv -f plotfile $output_name`;
	unlink ($con_c);
}

sub compare_tree_by_tcoffee
{
	$t_coffee_cmd="t_coffee -other_pg seq_reformat";
	$action=" -action +tree_cmp";
	$extract_cmd = "|awk '/T\: [0-9]+ W\:/ {print \$2}'|";
	$tmp_file="tmp.txt";
	$score_file="result.csv";

	print "[STRAT] Compare Tree by T_coffee tree_cmp\n";

	`echo -n $pro_name "," >> $score_file`;
	for my $index1 (0 .. $#input_files)
	{
		$score[$index1][$index1]=100;
		for my $index2 (($index1+1) .. $#input_files)
		{
			$cmd=$t_coffee_cmd." -in ".$input_files[$index1]." -in2 ".$input_files[$index2].$action.$extract_cmd;
 			print $cmd."\n";
   			open(SCORE, $cmd);
   			$score_value = <SCORE>;
   			close(SCORE);
			chomp($score_value);
			$score[$index1][$index2]=$score_value;
			$score[$index2][$index1]=$score_value;
			`echo -n $score_value "," >> $score_file`;
		}
		if(!$all)
		{
			`echo >> $score_file`;
			last;
		}
	}

	print "\nTree Similarity between all pairs of trees in tree file:\n\n";
	print "\t";
	for my $index1 (0 .. $#input_files)
	{
		print ($index1+1);	print "\t";
	}
	print "\n";

	for my $index1 (0 .. $#input_files)
	{
		print ($index1+1);	print "\t";
		for my $index2 (0 .. $#input_files)
		{
			print "$score[$index1][$index2]\t";
		}
		print "\n";
		if(!$all)
		{
			last;		
		}
	}

	print "\n[END] Compare Tree by T_coffee tree_cmp\n";
}

sub get_prefix_name
{
	($name) = @_;
	$prefix_name = $name;
	if($name =~ /.+\/\b(.+)\..+$/)
	{
		$prefix_name=$1;
	}
	elsif($name =~ /(.+)\..+$/)
	{
		$prefix_name=$1;
	}
	$prefix_name;
}

