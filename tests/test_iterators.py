import random

import numpy as np
import pysam

from pygenlib.genemodel import *
from pygenlib.iterators import *
from pygenlib.utils import TagFilter, toggle_chr
import pytest
import os
from pathlib import Path
from itertools import product
from more_itertools import take
import pandas as pd
from dataclasses import dataclass

@pytest.fixture(autouse=True)
def base_path() -> Path:
    """Go to testdata dir"""
    testdir = Path(__file__).parent.parent / "testdata/"
    print("Setting working dir to %s" % testdir)
    os.chdir(testdir)
    return testdir

@pytest.fixture(autouse=True)
def testdata() -> pd.DataFrame:
    # Some overlap tests
    # .........1........  ....2......
    # |-a-|
    #      |-b-|
    #   |-c-|
    #           |-d-|
    #                         |-e-|
    #                     |-f--------|
    #                         |-g-|
    #                         |--h---|
    d = {
        'a': gi('1', 1, 10),
        'b': gi('1', 11, 20),
        'c': gi('1', 5, 15),
        'd': gi('1', 30, 40),
        'e': gi('2', 21, 30),
        'f': gi('2', 1, 50),
        'g': gi('2', 21, 30),
        'h': gi('2', 21, 50),
    }
    df = pd.DataFrame([(loc.chromosome, loc.start, loc.end, name) for name, loc in d.items()],
                      columns=['Chromosome', 'Start', 'End', 'Name'])  # note: this df is not sorted!
    return d, df

def loc_list(s):
    return [gi.from_str(x) for x in s.split(',')]

def test_DictIterator(base_path, testdata):
    d,df=testdata
    assert len(DictIterator(d).take()) == len(d)
    assert DictIterator(d, '2', 10, 20).take()==[(gi.from_str('2:1-50'), 'f')]
    # with aliasing
    assert DictIterator(d, 'chr2', 10, 20, fun_alias=toggle_chr).take() == [(gi.from_str('chr2:1-50'), 'f')]

def test_FastaIterator(base_path):
    fasta_file='ACTB+SOX2.fa.gz'
    # read seq via pysam
    with pysam.Fastafile(fasta_file) as fh:
        ref={c:fh.fetch(c) for c in fh.references}
    # consume all
    all=''.join([s for _,s in FastaIterator(fasta_file, 'chr3', width=1, step=1).take()])
    assert(all==ref['chr3'])
    # with aliasing
    all=''.join([s for _,s in FastaIterator(fasta_file, '3', width=1, step=1, fun_alias=toggle_chr).take()])
    assert(all==ref['chr3'])
    # some edge cases where the provided sequence is shorter than the requested window size
    assert FastaIterator(fasta_file, 'chr7', 3, 6, width=5, step=3, padding=False).take() == [(gi('chr7', 3, 7), 'GTGCN')] # 5-mer from region of size 4, wo padding
    assert FastaIterator(fasta_file, 'chr7', 3, 6, width=5, step=3, padding=True).take() == [(gi.from_str('chr7:1-5'), 'NNGTG'), (gi.from_str('chr7:4-8'), 'TGCNN')] # 5-mer from region of size 4, wiwth padding
    # consume in tiling windows
    tiled = ''.join([s for _, s in FastaIterator(fasta_file, 'chr7', None, None, width=3, step=3).take()])
    assert(tiled[:-1]==ref['chr7']) # NOTE cut last char in tiled as it is padded by a single N (as len(ref['chr7']) % 3 = 2)
    # get the first 10 5-mers with and w/o padding
    fivemers = [s for _,s in FastaIterator(fasta_file, 'chr7', None, None, width=5, step=2, padding=False).take()][:10]
    assert fivemers==['TTGTG','GTGCC','GCCAT','CATTA','TTACA','ACACT','ACTCC','TCCAG','CAGCC','GCCTG']
    fivemers= [s for _,s in FastaIterator(fasta_file, 'chr7', None, None, width=5, step=2, padding=True).take()][:10]
    assert fivemers==['NNTTG','TTGTG','GTGCC','GCCAT','CATTA','TTACA','ACACT','ACTCC','TCCAG','CAGCC']
    # get 11-mers with padding
    ctx=[s for _, s in FastaIterator(fasta_file, 'chr7', 1, 10, width=11, step=1, padding=True)]
    assert ctx[:5]==['NNNNNTTGTGC','NNNNTTGTGCC','NNNTTGTGCCA','NNTTGTGCCAT','NTTGTGCCATT']
    assert ''.join([x[5] for x in ctx])==ref['chr7'][:10]


def test_TabixIterator(base_path):
    vcf_file = 'test_snps.vcf.gz'
    bed_file = 'test.bed.gz'
    bedg_file = 'test.bedgraph.gz'  # includes track header
    # read VCF file as TSV
    ti=TabixIterator(vcf_file, region='1:1-10', coord_inc=[0, 0], pos_indices=[0, 1, 1])
    assert(merge_yields(ti.take())[0] == gi('1', 1, 10))
    ti=TabixIterator(vcf_file, chromosome='1', coord_inc=[0, 0], pos_indices=[0, 1, 1])
    assert(merge_yields(ti.take())[0] == gi('1', 1, 20))
    ti = TabixIterator(vcf_file, chromosome='2', coord_inc=[0, 0], pos_indices=[0, 1, 1])
    assert len([(l,t) for l, t in ti.take()])==1
    with pytest.raises(AssertionError) as e_info:
        TabixIterator(vcf_file, 'unknown_contig',5,10)
    print(f'Expected assertion: {e_info}')
    # BED file with added 'chr' prefix
    ti=TabixIterator(bed_file, 'chr1', 1, 10, coord_inc = [1, 0], fun_alias=toggle_chr)
    assert(merge_yields(ti.take())[0] == gi('chr1', 6, 15)) # start is 0-based, end is 1-based
    # bedgraph file but parsed as Tabixfile
    assert sum([float(r[3])*len(l) for l, r in TabixIterator(bedg_file, coord_inc=[1, 0]).take()])==pytest.approx(7.425)



def test_GFF3Iterator(base_path):
    gff_file='gencode.v39.ACTB+SOX2.gff3.gz'
    stats=Counter()
    for loc, info in GFF3Iterator(gff_file):
        stats[info['feature_type']]+=1
    assert stats == {'exon': 106, 'CDS': 60, 'five_prime_UTR': 33, 'transcript': 24, 'three_prime_UTR': 20, 'start_codon': 17, 'stop_codon': 13, 'gene': 2}
    # GTF with aliasing
    gtf_file = 'ensembl_Homo_sapiens.GRCh38.109.ACTB+SOX2.gtf.gz'
    stats = Counter()
    for loc, info in GFF3Iterator(gtf_file, 'chr7', fun_alias=toggle_chr):
        stats[info['feature_type']] += 1
    assert stats=={'exon': 105,'CDS': 59,'five_prime_utr': 32,'transcript': 23,'three_prime_utr': 19,'start_codon': 16,'stop_codon': 12,'gene': 1}

def test_PandasIterator(base_path, testdata):
    d,df=testdata
    it = PandasIterator(df, 'Name')
    assert {k:v for v,k in it}==d
    # with aliasing
    it = PandasIterator(df, 'Name', fun_alias=toggle_chr)
    d1={n:gi('chr'+l.chromosome,l.start,l.end,l.strand) for n,l in d.items()}
    assert {k:v for v,k in it}==d1

def test_BlockLocationIterator(base_path, testdata):
    with BlockLocationIterator(TabixIterator('test.bed.gz', coord_inc = [1, 0], fun_alias=toggle_chr), strategy=BlockStrategy.OVERLAP) as it:
        locs=[l for l,_ in it]
        assert locs == loc_list('chr1:6-15,chr2:10-150')
    d, df = testdata
    assert [l for l, _ in BlockLocationIterator(PandasIterator(df, 'Name'), strategy=BlockStrategy.OVERLAP)] == loc_list('1:1-20,1:30-40 ,2:1-50')
    assert BlockLocationIterator(PandasIterator(df, 'Name'), strategy=BlockStrategy.LEFT).take()[-1][1][1] == ['e', 'g', 'h'] # same start coord
    assert BlockLocationIterator(PandasIterator(df, 'Name'), strategy=BlockStrategy.RIGHT).take()[-2][1][1] == ['e', 'g'] # same end coord
    assert BlockLocationIterator(PandasIterator(df, 'Name', fun_alias=toggle_chr), strategy=BlockStrategy.RIGHT).take()[-2][1][1] == \
           ['e', 'g']  # with aliasing
    right_sorted= BlockLocationIterator(PandasIterator(df.sort_values(['Chromosome', 'End']), 'Name', is_sorted=True), strategy=BlockStrategy.RIGHT)
    assert [x[1] for _, x in right_sorted.take()[-2:]] ==  [['e', 'g'], ['f', 'h']]


def test_SyncPerPositionIterator(base_path, testdata):
    class SyncPerPositionIteratorTestDataset():
        """ 2nd, slow implementation of the sync algorithm for testing"""

        def __init__(self, seed=None, n_it=3, n_pos=10, n_chr=2, n_int=5):
            self.seed = seed
            if seed:
                random.seed(seed)
            self.dat = {}
            self.minmax = {}
            for it in range(n_it):
                self.dat[f'it{it}'] = {}
                for chrom in range(n_chr):
                    self.dat[f'it{it}'][f'c{chrom}'] = self.create_rnd_int(it, f'c{chrom}', n_int, n_pos)

        def __repr__(self):
            return f"SyncPerPositionIteratorTestDataset({self.seed})"

        def create_rnd_int(self, it, chrom, n_int, n_pos):
            random.seed(self.seed)
            ret = []
            for i in range(random.randrange(n_int)):
                start = random.randrange(n_pos)
                end = random.randrange(start, n_pos)
                g = gi(chrom, start, end)
                g.testname = f'it{it}_{chrom}:{g.start}-{g.end}_{len(ret)}'
                g.idx = it
                if g.chromosome not in self.minmax:
                    self.minmax[g.chromosome] = range(g.start, g.end)
                self.minmax[g.chromosome] = range(min(self.minmax[g.chromosome].start, g.start),
                                                  max(self.minmax[g.chromosome].stop, g.end))
                ret.append(g)
            return list(sorted(ret))

        def expected(self):
            ret = []
            for chrom in sorted(self.minmax):
                for p in range(self.minmax[chrom].start, self.minmax[chrom].stop + 1):
                    pos = gi(chrom, p, p)
                    found = []
                    for i, d in enumerate(self.dat.values()):
                        for g in d[chrom]:
                            if g.overlaps(pos):
                                found.append(g)
                    list.sort(found)
                    ret.append((pos, (found, [g.idx for g in found], [g.testname for g in found])))
            return ret

        def found(self):
            """ Iterate with SyncPerPositionIterator() over DictIterators """
            ret = {}
            for it in self.dat:
                gis = []
                for c in self.dat[it]:
                    gis.extend(self.dat[it][c])
                ret[it] = gis
            return SyncPerPositionIterator([DictIterator({g.testname: g for g in ret[it]}) for it in ret]).take()
    # a = {
    #     'a1': gi('1', 3, 5),
    #     'a2': gi('1', 10, 15),
    # }
    # b = {
    #     'b1': gi('1', 1, 5),
    #     'b2': gi('1', 2, 6)
    # }
    # c = {
    #     'c1': gi('1', 2, 3),
    #     'c2': gi('1', 2, 7),
    #     'c3': gi('1', 2, 7)
    # }
    # d = {
    #     'd1': gi('2', 1, 5)
    # }
    # for x in [a,b,c,d]:
    #     print(x)
    # it = SyncPerPositionIterator([DictIterator(a), DictIterator(b), DictIterator(c), DictIterator(d)])
    # for x in it:
    #     print(x)

    # test with random datasets
    found_differences=set()
    for seed in range(0,1000):
        print(f"======================================={seed}============================")
        t=SyncPerPositionIteratorTestDataset(seed)
        assert len(t.found()) == len(t.expected()), f"invalid length for {t}, {len(t.found())} != {len(t.expected())}"
        for a,b in zip(t.found(), t.expected()):
            if a!=b:
                if SortedSet(a[1][0])!=SortedSet(b[1][0]):
                    found_differences.add(seed)
    assert len(found_differences)==0
    # use more intervals other params
    found_differences=set()
    for seed in range(0,10):
        print(f"======================================={seed}============================")
        t=SyncPerPositionIteratorTestDataset(seed, n_it=5, n_pos=100, n_chr=5, n_int=500)
        assert len(t.found()) == len(t.expected()), f"invalid length for {t}, {len(t.found())} != {len(t.expected())}"
        for a,b in zip(t.found(), t.expected()):
            if a!=b:
                if SortedSet(a[1][0])!=SortedSet(b[1][0]):
                    found_differences.add(seed)
    assert len(found_differences)==0
    # for seed in found_differences:
    #     t=SyncPerPositionIteratorTestDataset(seed)
    #     print(f"differences in {t}")
    #     for a, b in zip(t.found(), t.expected()):
    #         if a != b:
    #             print('>', a, b)

def test_PyrangesIterator(base_path):
    exons, cpg = pr.data.exons(), pr.data.cpg()
    # get exons with same start but different end coords
    res=[]
    for mloc, (locs, ex) in BlockLocationIterator(PandasIterator(exons.df, 'Name')):
        endpos={ l.end for l in locs}
        if len(endpos)>1:
            res+=[(mloc, (locs, ex))]
    assert len(res)==5

@dataclass
class MockRead:
    tags: dict
    def has_tag(self, tag):
        return tag in self.tags
    def get_tag(self, tag):
        return self.tags.get(tag)

def test_TagFilter():
    assert TagFilter('xx', [1,12,13], False).filter(MockRead({'xx':12}))  # filter if values is found
    assert not TagFilter('xx', [12], False, inverse=True).filter(MockRead({'xx':12})) # inverse filter: filter if values is not found!

def test_ReadIterator(base_path):
    with ReadIterator('rogue_read.bam', 'SIRVomeERCCome') as it:
        for l,r in it:
            pass
        assert it.stats['n_reads', 'SIRVomeERCCome']==1
    stats={x:Counter() for x in ['all', 'def', 'mq20', 'tag']}
    with open_file_obj('small_example.bam') as bam:
        for chrom in get_reference_dict(bam):
            with ReadIterator(bam, chrom, flag_filter=0) as it:
                it.take()
                stats['all'].update(it.stats)
            with ReadIterator(bam, chrom) as it:
                it.take()
                stats['def'].update(it.stats)
            with ReadIterator(bam, chrom, min_mapping_quality=20) as it:
                it.take()
                stats['mq20'].update(it.stats)
            with ReadIterator(bam, chrom, tag_filters=[TagFilter('MD', ['100'])]) as it:
                it.take()
                stats['tag'].update(it.stats)
    #print( stats['tag'])
    assert stats['all']['n_reads', '1']==31678 # samtools view -c small_example.bam -> 31678
    assert stats['def']['n_reads', '1']==21932 # samtools view -c small_example.bam -F 3844 -> 21932
    assert stats['mq20']['n_reads', '1']==21626 # samtools view -c small_example.bam -F 3844 -q 20 -> 21626
    assert stats['tag']['n_reads', '1'] == 7388  # samtools view  small_example.bam -F 3844 | grep -v "MD:Z:100" | wc -l -> 7388
    # count t/c mismatches
    tc_conv={}
    for l,(r,mm) in ReadIterator('small_example.bam',report_mismatches=True, min_base_quality=10):
        if len(mm)>0:
            is_rev = not r.is_reverse if r.is_read2 else r.is_reverse
            refc = "A" if is_rev else "T"
            altc = "G" if is_rev else "C"
            mm_tc=[(off, pos1, ref, alt) for off, pos1, ref, alt in mm if ref==refc and alt==altc]
            if len(mm_tc) > 0:
                tc_conv[r.query_name, not r.is_read2]=mm_tc
    # overlapping mate pair: both  contain T/C snp
    assert tc_conv['HWI-ST466_135068617:8:2209:6224:33460', True]== [(71, 22432587, 'T', 'C')]
    assert tc_conv['HWI-ST466_135068617:8:2209:6224:33460', False] == [(29, 22432587, 'T', 'C')]
    #  a read with 2 A/G conversions
    assert tc_conv['HWI-ST466_135068617:8:2316:4251:54002', False]==[(2, 22443997, 'A', 'G'), (5, 22444000, 'A', 'G')]
    # test aliasing
    assert len(ReadIterator('small_example.bam', 'chr1',fun_alias=toggle_chr).take())==21932
    # TODO add data from /groups/.../ref/testdata/smallbams/

def slow_pileup(bam, chrom,start,stop):
    """ Runs pysam pileup for reference """
    ac=Counter()
    for pu in bam.pileup(contig=chrom, start=start - 1, stop=stop - 1, flag_filter=DEFAULT_FLAG_FILTER,
                         truncate=True, mark_ends=True, add_indels=True, min_base_quality=0, min_mapping_quality=0,
                         ignore_overlaps=False, ignore_orphans=False,
                         max_depth=100000):
        pos = pu.reference_pos + 1
        ac[pos] = Counter()
        for r in pu.pileups:
            if r.is_refskip:
                continue
            # print(r.alignment.query_name, r.query_position)
            if r.is_del:
                ac[pos][None] += 1
            else:
                ac[pos][r.alignment.query_sequence[r.query_position]] += 1
    return [(gi(chrom, gpos, gpos), ac[gpos] if gpos in ac else Counter()) for gpos in range(start, stop)]


def test_FastPileupIterator(base_path):
    with open_file_obj('small_example.bam') as bam:
        # A T/C SNP
        assert [(l.start,c) for l,c in FastPileupIterator(bam, '1', {22432587})]==[(22432587, Counter({'C': 4}))]
        # 2 positions with  single MM
        assert [(l.start,c) for l,c in FastPileupIterator(bam, '1', {22433446,22433447})]==[(22433446, Counter({'G': 3, 'T': 1})), (22433447, Counter({'C': 3, 'G': 1}))]
        # A G/T SNP with 3 low-quality bases
        assert [(l.start,c) for l,c in FastPileupIterator(bam, '1', {22418286}, min_base_quality=10)]==[(22418286, Counter({'T': 12, 'G': 2}))]
        # position with 136 Ts and 1 deletion
        assert [(l.start,c) for l,c in FastPileupIterator(bam, '1', {22418244})]==[(22418244, Counter({'T': 136, None: 1}))]
        # assert that also uncovered positions are reported
        assert [(l.start,c) for l,c in FastPileupIterator(bam, '1', range(22379012,22379015))]==[(22379012, Counter()),(22379013, Counter()), (22379014, Counter({'C': 1}))]
        # assert equal to slow pysam pileup. This region contains uncovered areas, insertions and deletions: chr1:22,408,208-22,408,300
        assert FastPileupIterator(bam, '1', range(22408208,22408300)).take()==slow_pileup(bam, '1', 22408208,22408300)
        # test aliasing
        assert [(l.start, c) for l, c in FastPileupIterator(bam, 'chr1', {22418244}, fun_alias=toggle_chr)] == [
            (22418244, Counter({'T': 136, None: 1}))]

def test_FastqIterator(base_path):
    fastq_file='test.fq.gz'
    assert len(FastqIterator(fastq_file))==4
    assert [len(x[1]) for x in FastqIterator(fastq_file)]==[34, 26, 24, 37]
    # iterate PE reads and assert names contain 1/2
    for r1,r2 in zip(FastqIterator('Test01_L001_R1_001.top20.fastq'), FastqIterator('Test01_L001_R2_001.top20.fastq')):
        n1=r1.name.split(' ')[1].split(':')[0]
        n2 = r2.name.split(' ')[1].split(':')[0]
        assert n1=='1' and n2=='2'

def test_VcfIterator(base_path):
    """TODO: test INDELs"""
    vcf_file = 'test.vcf.gz'
    with VcfIterator(vcf_file) as it:
        assert [v.GT for _,v in it.take()]==[{'SAMPLE':'1/1'}]*3
        assert [v.CS for _,v in it.take()]==[{'SAMPLE':'A'},{'SAMPLE':'B'},{'SAMPLE':'C'}]
        assert [v.zyg for _,v in it.take()]==[{'SAMPLE':2}]*3
        assert [l.start for l,_ in it.take()]==[100000,200000,300000]

    # with sample filtering
    vcf_file='dmelanogaster_6_exported_20230523.vcf.gz'
    with VcfIterator(vcf_file, samples=['DGRP-208', 'DGRP-325', 'DGRP-721']) as it:
        dat=it.take()
        assert len(dat)==25 # there are 25 variants called in at least one of the 3 samples
        # NOTE: 2nd var is a no call (./.) in this sample!
        assert [v.zyg['DGRP-208'] for _,v in dat] == [2, None, 2, 2, 0, 0, 2, 0, 0, 2, 0, 0, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 2]

def test_BedIterator(base_path):
    bed_file='test.bed.gz'
    bedg_file = 'test.bedgraph.gz'

    # simple test
    assert len(BedIterator(bed_file).take()) == 3

    # annotate all intervals with values from 2 bedgraph iterators
    for l,d in BedIterator(bed_file).annotate([BedGraphIterator(bedg_file),BedGraphIterator(bedg_file)], ['val1','val2']):
        d.val1 = None if len(d.val1)==0 else np.mean(d.val1)
        d.val2 = None if len(d.val2)==0 else np.mean(d.val2)
        print(l, d, d.val1, d.val2)
        assert d.val1 == d.val2

def test_vcf_and_gff_it(base_path):
    """TODO: expand"""
    gff_file = 'flybase.dmel-all-r6.51.sorted.gtf.gz'
    vcf_file = 'dmelanogaster_6_exported_20230523.vcf.gz'
    for x in GFF3Iterator(gff_file, '2L', 574299, 575733).annotate(
        VcfIterator(vcf_file, samples=['DGRP-208', 'DGRP-325', 'DGRP-721']), 'variant'):
        print(x, x.variant)

def test_transcriptome_iterator(base_path):
    config = {
        'genome_fa': 'ACTB+SOX2.fa.gz',
        'genome_offsets': {'chr3': 181711825, 'chr7': 5526309},
        'annotation_gff': 'gencode.v39.ACTB+SOX2.gff3.gz',
        'annotation_flavour': 'gencode',
        'transcript_filter': {
            'included_tids': ['ENST00000473257.3']
        },
        'drop_empty_genes': True
    }
    t=Transcriptome(config)


    # annotate
    bedg_file = 'GRCh38.k24.umap.ACTB_ex1+2.bedgraph.gz'
    for l, ex in t.annotate(Exon, BedGraphIterator(bedg_file), 'val1'):
        print(ex)

    for l, ex in TranscriptomeIterator(t, feature_types=(Exon)).annotate(BedGraphIterator(bedg_file), 'mappability'):
        print(l, ex, ex.mappability if hasattr(ex, 'mappability') else None)



    # iterate exons and introns only
    with TranscriptomeIterator(t, feature_types=(Exon,Intron)) as it:
        for feature in it:
            print(feature, feature.__dict__)
