"""
===========================
Pipeline gatk4
===========================

.. Replace the documentation below with your own description of the
   pipeline's purpose

Overview
========

This pipeline computes the word frequencies in the configuration
files :file:``pipeline.ini` and :file:`conf.py`.

Usage
=====

See :ref:`PipelineSettingUp` and :ref:`PipelineRunning` on general
information how to use CGAT pipelines.

Configuration
-------------

The pipeline requires a configured :file:`pipeline.ini` file.
CGATReport report requires a :file:`conf.py` and optionally a
:file:`cgatreport.ini` file (see :ref:`PipelineReporting`).

Default configuration files can be generated by executing:

   python <srcdir>/pipeline_@template@.py config

Input files
-----------

None required except the pipeline configuration files.

Requirements
------------

The pipeline requires the results from
:doc:`pipeline_annotations`. Set the configuration variable
:py:data:`annotations_database` and :py:data:`annotations_dir`.

Pipeline output
===============

.. Describe output files of the pipeline here

Glossary
========

.. glossary::


Code
====

"""
from ruffus import *
import sys
import os
import gzip
import CGAT.Experiment as E
import CGATPipelines.Pipeline as P

# load options from the config file
PARAMS = P.getParameters(
    ["%s/pipeline.ini" % os.path.splitext(__file__)[0],
     "../pipeline.ini",
     "pipeline.ini"])


########## Read QC ########## 

@follows(mkdir("fastqc"))
@transform("*.fastq.*.gz", regex(r"(\S+).fastq.(\S+).gz"), r"fastqc/\1_read\2_fastqc.log")
def run_fastqc(infile, outfile):
    '''Run fastqc on raw reads '''
    statement = '''fastqc -o fastqc --nogroup --extract %(infile)s >& %(outfile)s '''
    P.run()


@follows(mkdir("report"))
@merge(run_fastqc, "report/fastqc.html")
def fastqc_report(infiles, outfile):
    statement = '''LANG=en_GB.UTF-8 multiqc fastqc 
                        --filename report/fastqc &> %(outfile)s.log '''
    P.run()


########## Trimming ########## 


@follows(mkdir("trimmed"))
@transform("*.fastq.1.gz", regex(r"(\S+).fastq.1.gz"), r"trimmed/\1.trim.fastq.1.gz")
def trim_reads(infile, outfile):
    '''trim reads to find guide RNA '''
    job_threads = int(PARAMS['trim_threads'])
    infile2 = infile.replace(".fastq.1.gz", ".fastq.2.gz")
    outfile2 = outfile.replace(".fastq.1.gz", ".fastq.2.gz")
    outfile1_unpaired = outfile.replace(".fastq.1.gz", ".unpaired.fastq.1.gz")
    outfile2_unpaired = outfile.replace(".fastq.1.gz", ".unpaired.fastq.2.gz")
    statement = '''trimmomatic PE 
                    -threads %(trim_threads)s
                    -trimlog %(outfile)s.log
                    %(infile)s %(infile2)s
                    %(outfile)s %(outfile1_unpaired)s
                    %(outfile2)s %(outfile2_unpaired)s
                    %(trim_options)s
                    ''' 
    P.run()

@follows(trim_reads)
@transform("trimmed/*.fastq.*.gz", regex(r"trimmed/(\S+).trim.fastq.(\S+).gz"), r"trimmed/\1_read\2_fastqc.log")
def run_trimmed_fastqc(infile, outfile):
    '''Run fastqc on trimmed reads '''
    statement = '''fastqc -o trimmed --nogroup --extract %(infile)s >& %(outfile)s'''
    P.run()

@follows(mkdir("report"))
@merge(run_trimmed_fastqc, "report/trimming_statistics.html")
def trimmed_fastqc_report(infiles, outfile):
    statement = '''LANG=en_GB.UTF-8 multiqc trimmed/*.log trimmed/
                        --filename report/trimming_statistics &> %(outfile)s.log'''
    P.run()
    
    
########## Mapping ########## 


@follows(mkdir("unmapped_bam"))
@transform("*.fastq.1.gz",
           regex(r"(.*).fastq.1.gz"),
           r"unmapped_bam/\1.unal.bam")
def FastQtoSam(infile, outfile):
    '''returns an unaligned bam file'''
    infile2 = infile.replace(".fastq.1.gz", ".fastq.2.gz")
    filename = P.snip(os.path.basename(infile),".fastq.1.gz").split("-")
    sm = filename[0] + "-" + filename[1]
    with gzip.open(infile, 'rb') as inf:
        line1 = str(inf.readline())
        fields = line1.split(":")
        rg = fields[2] + "_" + fields[3]
        first = False
    # the command line statement we want to execute
    statement = '''picard -Xmx32G FastqToSam 
                    F1=%(infile)s F2=%(infile2)s 
                    O=%(outfile)s 
                    SM=%(sm)s 
                    RG=%(rg)s 
                    PL=ILLUMINA'''
    P.run()


@follows(mkdir("rg_fastq"))
@transform(FastQtoSam,
           regex(r"unmapped_bam/(.*).unal.bam"),
           r"rg_fastq/\1.rg.fastq.1.gz")
def SamToFastQ(infile, outfile):
    '''returns a pair of fastq files'''
    outfile2 = outfile.replace(".fastq.1.gz", ".fastq.2.gz")
    # the command line statement we want to execute
    statement = '''picard -Xmx32G SamToFastq 
                    I=%(infile)s
                    FASTQ=%(outfile)s SECOND_END_FASTQ=%(outfile2)s'''
    P.run()


@follows(mkdir("mapping"))
@transform(SamToFastQ,
           regex(r"rg_fastq/(.*).rg.fastq.1.gz"),
           r"mapping/\1.bam")
def bwamem(infile, outfile):
    '''maps the fastq files'''
    infile2 = infile.replace(".fastq.1.gz", ".fastq.2.gz")
    # the command line statement we want to execute
    job_threads = int(PARAMS['bwa_cores'])
    job_memory = '2G'
    statement = '''bwa mem -t %(bwa_cores)s -M %(bwa_index)s 
                    %(infile)s  %(infile2)s
                    | samtools view -b - > %(outfile)s 2> %(outfile)s.log'''
    P.run()


@follows(mkdir("merge_bam_alignment"))
@transform(bwamem,
           regex(r"mapping/(.*).bam"),
           r"merge_bam_alignment/\1.mergali.bam")
def merge_bam_alignment(infile, outfile):
    '''merges the unmapped and mapped bam files'''
    infile2 = infile.replace("mapping", "unmapped_bam").replace(".bam", ".unal.bam")
    # the command line statement we want to execute
    job_memory = '64G'
    # export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=${TMPDIR}" &&
    statement = ''' /usr/bin/time -o %(outfile)s.time -v
                    picard -Xmx64G MergeBamAlignment 
                    USE_JDK_DEFLATER=true
                    USE_JDK_INFLATER=true
                    TMP_DIR=${TMPDIR}/${USER}
                    ALIGNED=%(infile)s 
                    UNMAPPED=%(infile2)s
                    O=%(outfile)s
                    R=%(bwa_index)s
                    2> %(outfile)s.stderr &&
                    hostname > %(outfile)s.host'''
    P.run()
    
@follows(mkdir("merge_sam")) 
@collate(merge_bam_alignment,
           regex(r"merge_bam_alignment/(.*)-lane\d.mergali.bam"),
           r"merge_sam/\1.mergsam.bam")
def merge_sam(infiles, outfile):
    '''merges the files from different flow cell lanes into one'''
    #need to write code that will take multiple infiles and merge them
    job_memory = '32G'
    statement = '''picard -Xmx32G MergeSamFiles'''
    
    for e in infiles:
        statement = statement + ' I={}'.format(e)
    statement = statement + ' O={}'.format(outfile)
    # the command line statement we want to execute
            
    P.run()
 

@follows(mkdir("mark_duplicates"))
@transform(merge_sam,
           regex(r"merge_sam/(.*).mergsam.bam"),
           r"mark_duplicates/\1.md.bam")
def mark_duplicates(infile, outfile):
    '''marks duplicates'''
    outfile2 = outfile.replace(".md.bam", ".md.txt")
    # the command line statement we want to execute
    job_memory = '16G'
    statement = '''picard -Xmx16G MarkDuplicates
                    USE_JDK_DEFLATER=true
                    USE_JDK_INFLATER=true
                    TMP_DIR=${TMPDIR}/${USER}
                    I=%(infile)s
                    O=%(outfile)s 
                    M=%(outfile2)s
                    >& %(outfile)s.log'''        
    P.run()
    
@follows(mkdir("bqsr"))
@transform(mark_duplicates,
           regex(r"mark_duplicates/(.*).md.bam"),
           r"bqsr/\1.bqsr.table")
def bqsr(infile, outfile):
    '''creates a base score recalibration table'''
    # the command line statement we want to execute
    statement = ''' gatk BaseRecalibrator 
                    -I=%(infile)s
                    -R=%(bwa_index)s 
                    --known-sites %(dbsnp)s
                    -O=%(outfile)s
                    >& %(outfile)s.log'''
                    
    P.run()
    
    
@follows(mkdir("apply_bqsr"))
@follows(mark_duplicates)
@transform(bqsr,
           regex(r"bqsr/(.*).bqsr.table"),
                 r"apply_bqsr/\1.recalibrated.bam")
def apply_bqsr(infile, outfile):
    '''recalibrates the bam files'''
    # the command line statement we want to execute
    infile_bam = "mark_duplicates/" + P.snip(os.path.basename(infile), "bqsr.table") + "md.bam"
    
    statement = '''gatk ApplyBQSR 
                   -R=%(bwa_index)s
                   -I=%(infile_bam)s
                   --bqsr-recal-file %(infile)s 
                   -O=%(outfile)s
                   >& %(outfile)s.log''' 



    P.run()
    
    
  
@follows(mkdir("mutect2"))
@follows(apply_bqsr)
@transform(apply_bqsr,
           regex(r"apply_bqsr/([A-Z][0-9]_[0-9])(-tumour).recalibrated.bam"),
           r"mutect2/\1.pid")

def patientID(infiles, outfile):
    '''makes and empty file for patient ID'''
    '''patient sample names should start with capital letters followed by numbers'''
    '''might need to change it for different patient names'''
    to_cluster = False
    statement = '''touch %(outfile)s'''

    

    P.run()

@follows(patientID) 
@transform(patientID, 
           regex(r"mutect2/(.*).pid"),
                r"mutect2/\1.vcf")
def Mutect2(infile,outfile):
    basename = P.snip(os.path.basename(infile),".pid")
    infile_tumour = "apply_bqsr/" + basename + "-tumour.recalibrated.bam"   
    samplename_tumour = basename + "-tumour"   
    basename2 = basename.split("_")
    infile_control = "apply_bqsr/" + basename2[0] + "_1-control.recalibrated.bam"
    samplename_control = basename2[0] + "_1-control"
    statement = '''gatk Mutect2 
                     -R=%(bwa_index)s
                     -I=%(infile_tumour)s
                     -tumor %(samplename_tumour)s
                     -I=%(infile_control)s
                     -normal %(samplename_control)s
                     -O=%(outfile)s'''
                     
    P.run()
                     
@follows(mkdir("filter_mutect"))     
@transform(Mutect2, 
           regex(r"mutect2/(.*).vcf"),
                r"filter_mutect/\1.filtered.vcf")
def FilterMutect(infile,outfile):
    statement = '''gatk FilterMutectCalls
                    -V %(infile)s
                    -O %(outfile)s'''


    P.run()

                     
         
def full(bqsr):
    pass


def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)


if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
