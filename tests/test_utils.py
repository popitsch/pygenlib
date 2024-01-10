import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pysam
import pytest

from pygenlib.testdata import get_resource
from pygenlib.utils import reverse_complement, TMAP, complement, ParseMap, get_config, parse_gff_attributes, cmp_sets, \
    get_reference_dict, ReferenceDict, longest_hp_gc_len, kmer_search, split_list, intersect_lists, to_str, count_gc, \
    bgzip_and_tabix, gunzip, print_dir_tree, count_lines, count_reads, write_data, slugify, rnd_seq, gi, toggle_chr, \
    guess_file_format


@pytest.fixture(autouse=True)
def base_path() -> Path:
    """Go to testdata dir"""
    testdir = Path(__file__).parent.parent / "testdata/"
    print("Setting working dir to %s" % testdir)
    os.chdir(testdir)
    return testdir


def from_str(s):
    return [gi.from_str(x) for x in s.split(',')]


def test_reverse_complement():
    assert reverse_complement('ACTG') == "CAGT"
    assert reverse_complement('ACUG', TMAP['rna']) == "CAGU"
    assert reverse_complement('ACTG', TMAP['rna']) == "C*GU"
    assert complement('ACTG', TMAP['dna']) == "TGAC"
    assert complement('ACUG', TMAP['rna']) == "UGAC"
    tmap = ParseMap(TMAP['rna'], missing_char='?')  # custom unknown-base char
    assert complement('ACTG', tmap) == "UG?C"
    tmap = TMAP['rna']
    assert complement('ACTG', tmap) == "UG*C"


def test_get_config():
    config = json.loads('{ "obj1": { "obj2": { "prop1": 1 }}, "list1": [ "a", "b"], "prop2": 2 }')
    assert get_config(config, ['obj1', 'obj2', 'prop1']), 1
    assert get_config(config, 'obj1/obj2/prop1'), 1
    assert get_config(config, ['list1']), ["a", "b"]
    assert get_config(config, 'prop2'), 2
    assert get_config(config, 'prop3', 15), 15
    assert get_config(config, 'prop3') is None


def test_parse_gff_attributes(base_path):
    """ shallow test of GFF/GTF info field parsing.
    """
    from pygenlib.genemodel import gff_flavours
    for fn, dialect in [(get_resource('gencode_gff'), gff_flavours['gencode', 'gff']),
                        (get_resource('ucsc_gtf'), gff_flavours['ucsc', 'gtf']),
                        (get_resource('ensembl_gff'), gff_flavours['ensembl', 'gff']),
                        (get_resource('flybase_gtf'), gff_flavours['flybase', 'gtf'])
                        ]:
        expected_fields = {v for k, v in dialect.items() if k in ['gid', 'tid', 'tx_gid', 'feat_tid'] and v is not None}
        parsed_attributes = set()
        with pysam.TabixFile(fn, mode="r") as f:
            for row in f.fetch(parser=pysam.asTuple()):
                reference, source, ftype, fstart, fend, score, strand, phase, info = row
                parsed_attributes |= parse_gff_attributes(info, fmt=guess_file_format(fn)).keys()
        shared, _, _ = cmp_sets(set(parsed_attributes), expected_fields)
        assert shared == expected_fields, f"missing fields in {fn}"


def test_get_reference_dict(base_path):
    """Test reference dict implementation and aliasing"""
    assert get_reference_dict(get_resource('ensembl_gff'), fun_alias=toggle_chr).keys() == {'chr3', 'chr7'}
    assert get_reference_dict(get_resource('ensembl_gff')).orig.keys() == \
           get_reference_dict(get_resource('ensembl_gff'), fun_alias=toggle_chr).orig.keys()
    assert get_reference_dict(get_resource('ensembl_gff'), fun_alias=toggle_chr).alias('1') == 'chr1'
    # compare 2 refsets, one w/o chr prefix (ensembl) and one with (fasta file)
    assert ReferenceDict.merge_and_validate(
        get_reference_dict(get_resource('ensembl_gff'), fun_alias=toggle_chr),
        get_reference_dict(get_resource('ACTB+SOX2_genome'))
    ).keys() == {'chr3', 'chr7'}
    assert ReferenceDict.merge_and_validate(
        get_reference_dict(get_resource('ensembl_gff')),
        get_reference_dict(get_resource('ACTB+SOX2_genome'), fun_alias=toggle_chr)
    ).keys() == {'3', '7'}


def test_longest_hp_gc_len():
    assert longest_hp_gc_len("AAAAAA"), (6, 0)
    assert longest_hp_gc_len("AAAGCCAA"), (3, 3)
    assert longest_hp_gc_len("GCCGCGCGCGCGCGCAAAGCCAA"), (3, 15)
    assert longest_hp_gc_len("GCCGCGCGCGCGCCCCGCAAAGCCAA"), (4, 18)
    assert longest_hp_gc_len("ACTGNNNACTGC"), (3, 2)


def test_kmer_search():
    seq = "ACTGATACGATGCATCGACTAGCATCGACTACGATCAGCTACGATCGACTAACGCGAGCAC"
    res = kmer_search(seq, ['TACGA', 'ATCAG', 'AACGC'])
    for k in res:
        for s in res[k]:
            assert seq[s:s + len(k)], k


def test_split_list():
    split_list([1, 2, 3, 4, 5, 6], 3, is_chunksize=True)
    for i in [0, 1, 5, 20, 30]:
        assert len(list(split_list(range(i), 3))) == 3
    for x, y, z in [(0, 1, 0), (1, 1, 1)]:
        # print(list(split_list(range(x), y, is_chunksize=True)))
        assert len(list(split_list(range(x), y, is_chunksize=True))) == z


def test_intersect_lists():
    assert intersect_lists() == []
    assert intersect_lists([1, 2, 3, 4], [1, 4], [3, 1], check_order=True) == [1]
    assert intersect_lists([1, 2, 3, 4], [1, 4]) == [1, 4]
    assert intersect_lists([1, 2, 3], [3, 2, 1]) == [3, 2, 1]
    with pytest.raises(AssertionError) as e_info:  # assert that assertion error is raised
        intersect_lists([1, 2, 3], [3, 2, 1], check_order=True)
    print(f'Expected assertion: {e_info}')
    assert intersect_lists((1, 2, 3, 5), (1, 3, 4, 5)) == [1, 3, 5]


def test_to_str():
    assert to_str(), 'NA'
    assert to_str(na='*'), '*'
    assert to_str([12, [None, [1, '', []]]]), '12,NA,1,NA,NA'
    assert to_str(12, [None, [1, '', []]]), '12,NA,1,NA,NA'
    assert to_str(range(3), sep=';'), '0;1;2'
    assert to_str(1, 2, [3, 4], 5, sep=''), '12345'
    assert to_str([1, 2, 3][::-1], sep=''), '321'
    assert to_str((1, 2, 3)[::-1], sep=''), '321'


def test_rnd_seq():
    # we expect 50% GC
    gc_perc = np.array([count_gc(s)[1] for s in rnd_seq(100, m=1000)])
    assert 0.45 < np.mean(gc_perc) < 0.55
    # we expect 60% GC
    gc_perc = np.array([count_gc(s)[1] for s in rnd_seq(100, 'GC' * 60 + 'AT' * 40, 1000)])
    assert 0.55 < np.mean(gc_perc) < 0.65


def test_bgzip_and_tabix(base_path):
    # create temp dir, gunzip a GFF3 file and bgzip+tabix via pysam.
    # just asserts that file exists.
    with tempfile.TemporaryDirectory() as tmp:
        gunzip(get_resource('gencode_gff'), tmp + '/test.gff3')
        print('created temporary file', tmp + '/test.gff3')
        bgzip_and_tabix(tmp + '/test.gff3')
        assert os.path.isfile(tmp + '/test.gff3.gz') and os.path.isfile(tmp + '/test.gff3.gz.tbi')
        print_dir_tree(tmp)


def test_count_reads(base_path):
    assert count_lines('fastq/Test01_L001_R1_001.top20.fastq'), 80
    assert count_reads('fastq/Test01_L001_R1_001.top20.fastq'), 20


def test_write_data():
    assert write_data([1, 2, ['a', 'b', None], None], sep=';'), "1;2;a,b,NA;NA"


def test_slugify():
    assert slugify("this/is/an invalid filename!.txt"), "thisisan_invalid_filenametxt"


def test_reference_dict(base_path):
    r1 = ReferenceDict({'chr1': 1, 'chr2': 2, 'chrM': 23, 'chrX': 24}, "A", None)
    r2 = ReferenceDict({'chr1': 1, 'chrX': 24}, "B", None)
    r3 = ReferenceDict({'chr1': 1, 'chrX': 24, 'chrM': 23}, "C", None)  # different order
    r4 = ReferenceDict({'chr1': 1, 'chrX': 25}, "D", None)  # different length
    assert ReferenceDict.merge_and_validate() is None
    assert ReferenceDict.merge_and_validate(r1) == r1
    assert ReferenceDict.merge_and_validate(r1, r2) == {'chr1': 1, 'chrX': 24}
    with pytest.raises(AssertionError) as e_info:
        ReferenceDict.merge_and_validate(r1, r3, check_order=True)
    print(f'Expected assertion: {e_info}')
    assert ReferenceDict.merge_and_validate(r1, r2) == {'chr1': 1, 'chrX': 24}
    with pytest.raises(AssertionError) as e_info:
        ReferenceDict.merge_and_validate(r1, r4)
    print(f'Expected assertion: {e_info}')
    ReferenceDict.merge_and_validate(r1, None, r2)
    # test iter_blocks()
    r5 = ReferenceDict({'chr1': 10, 'chr2': 20, 'chrM': 23, 'chrX': 12}, "test_refdict", None)
    assert list(r5.iter_blocks(10)) == from_str(
        "chr1:1-10, chr2:1-10,  chr2:11-20, chrM:1-10,  chrM:11-20, chrM:21-23, chrX:1-10,  chrX:11-12")
