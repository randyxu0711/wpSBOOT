#!/bin/bash
# Allignment tool using : mafft muscle clustalw t_coffee
# command line : wpSBOOT.sh --infile --output --outfile
# 2 parts : 	1. calling 4 alignment tools	2. calling concatenate
# -- Parse option : -i for infile -o for outfile -p for path --

function usage()
{
	printf "\nHELP:-------------------------\n"
	printf "argument:\n-i for infile name\n-o for outfile name\n-p for path"	
	printf "\n------------------------------\n\n"
}

opcount=0
while getopts "i:o:p:m:?" argv
do
	case $argv in
		i)
			infile=$OPTARG
			echo " infile name is $infile"
			let "opcount++"
			;;
		o)
			outfile=$OPTARG
			echo " outfile name is $outfile"
			let "opcount++"
			;;
		p)
			path=$OPTARG
			echo " path is $path"
			let "opcount++"
			;;
		?)
			usage
			#printf "\nHELP:-------------------------\n"
			#printf "argument:\n-i for infile name\n-o for outfile name\n-p for path"	
			#printf "\n------------------------------\n\n"
			exit
			;;
	esac	
done

# -- Call 4 alignment tools --
function call4alntools()
{
	mkdir -p $path
	mafft $infile > 'mafft.fasta'
	mv ./'mafft.fasta' $path
	muscle -in $infile -out 'muscle.fasta'
	mv ./'muscle.fasta' $path
	clustalw -infile=$infile -outfile='clustalw.fasta' -output=fasta
	mv ./'clustalw.fasta' $path
	t_coffee -infile=$infile -outfile='tcoffee.fasta' -output=fasta
	mv ./'tcoffee.fasta' $path
	rm ./$outfile'.dnd'
}

#call4alntools

# -- Call concatenate.pl --
function callconcat()
{
	perl ./src/concatenate.pl --random --aln $path/'mafft.fasta' $path/'muscle.fasta' $path/'clustalw.fasta' $path/'tcoffee.fasta' --out 'result.phylip'
        mv ./'result.phylip' $path       
}

if [ $opcount -gt 0 ]; then 
	call4alntools 
	wait
	callconcat
fi
