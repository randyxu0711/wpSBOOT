#!/bin/bash
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
while getopts "i:o:p:?" argv
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
	mafft $infile > $outfile'_mafft'
	mv ./$outfile'_mafft' $path
	muscle -in $infile -fastaout $outfile'_muscle'
	mv ./$outfile'_muscle' $path
	clustalw -infile=$infile -outfile=$outfile'_clustalw' -output=fasta
	mv ./$outfile'_clustalw' $path
	t_coffee -infile=$infile -outfile=$outfile'_tcoffee' -output=fasta
	mv ./$outfile'_tcoffee' $path
	rm ./$outfile'.dnd'
}

#call4alntools

# -- Call concatenate.pl --
function callconcat()
{
	perl ./src/concatenate.pl --random --aln $path/$outfile'_mafft' $path/$outfile'_muscle' $path/$outfile'_clustalw' $path/$outfile'_tcoffee' --out $outfile'_superMSA.aln'
        mv ./$outfile'_superMSA.aln' $path       
}

if [ $opcount -gt 0 ]; then 
	call4alntools 
	callconcat
fi
