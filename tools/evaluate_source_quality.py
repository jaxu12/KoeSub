"""Prepare offline listening studies and report text vs. attested semantic errors.

Inputs contain completed model results; this tool performs no inference or
downloads and never marks imported captions as audio-audited automatically.
"""
import argparse
from pathlib import Path
import sys

from studio.source_evaluation import StudyStore,create_study,write_reports,quality_report,report_markdown


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('create');create.add_argument('--index',type=Path,required=True)
    create.add_argument('--results',type=Path,required=True);create.add_argument('--out',type=Path,required=True)
    report=commands.add_parser('report');report.add_argument('study',type=Path);report.add_argument('--out',type=Path,required=True)
    summary=commands.add_parser('summary');summary.add_argument('study',type=Path)
    args=parser.parse_args()
    if args.command=='create':
        study=create_study(args.index,args.results);StudyStore(args.out).save(study)
        print('Created:',args.out);print(report_markdown(quality_report(study)))
    else:
        study=StudyStore(args.study).load()
        result=write_reports(study,args.out,args.study) if args.command=='report' else quality_report(study)
        print(report_markdown(result))


if __name__=='__main__':main()
