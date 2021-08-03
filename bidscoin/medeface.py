#!/usr/bin/env python3
"""
A wrapper around the 'pydeface' defacing tool (https://github.com/poldracklab/pydeface) that computes
a defacing mask on an echo-combined image and then applies it to each individual echo-image.

This wrapper is fully BIDS-aware (a 'bidsapp') and writes BIDS compliant output

For single-echo data see `deface`
"""

import os
import shutil
import argparse
import json
import logging
import pandas as pd
import pydeface.utils as pdu
import drmaa
import nibabel as nib
import numpy as np
from pathlib import Path
try:
    from bidscoin import bidscoin, bids
except ImportError:
    import bidscoin, bids             # This should work if bidscoin was not pip-installed


def medeface(bidsdir: str, pattern: str, subjects: list, output: str, cluster: bool, nativespec: str, kwargs: dict):
    """

    :param bidsdir:     The bids-directory with the (multi-echo) subject data
    :param pattern:     Globlike search pattern (relative to the subject/session folder) to select the echo-images that need to be defaced, e.g. 'anat/*_T1w*'
    :param subjects:    List of sub-# identifiers to be processed (the sub- prefix can be left out). If not specified then all sub-folders in the bidsfolder will be processed
    :param output:      Determines where the defaced images are saved. It can be the name of a BIDS datatype folder, such as 'anat', or of the derivatives folder, i.e. 'derivatives'. If output is left empty then the original images are replaced by the defaced images
    :param cluster:     Flag to submit the deface jobs to the high-performance compute (HPC) cluster
    :param nativespec:  DRMAA native specifications for submitting deface jobs to the HPC cluster
    :param kwargs:      Additional arguments (in dict/json-style) that are passed to pydeface. See examples for usage
    :return:
    """

    # Input checking
    bidsdir = Path(bidsdir).resolve()

    # Start logging
    bidscoin.setup_logging(bidsdir/'code'/'bidscoin'/'deface.log')
    LOGGER.info('')
    LOGGER.info('------------ START multi-echo deface ----------')
    LOGGER.info(f">>> medeface bidsfolder={bidsdir} pattern={pattern} subjects={subjects} output={output}"
                f" cluster={cluster} nativespec={nativespec} {kwargs}")

    # Get the list of subjects
    if not subjects:
        subjects = bidscoin.lsdirs(bidsdir, 'sub-*')
        if not subjects:
            LOGGER.warning(f"No subjects found in: {bidsdir/'sub-*'}")
    else:
        subjects = ['sub-' + subject.replace('^sub-', '') for subject in subjects]              # Make sure there is a "sub-" prefix
        subjects = [bidsdir/subject for subject in subjects if (bidsdir/subject).is_dir()]

    # Prepare the HPC pydeface job submission
    with drmaa.Session() as pbatch:
        if cluster:
            jt                     = pbatch.createJobTemplate()
            jt.jobEnvironment      = os.environ
            jt.remoteCommand       = shutil.which('pydeface')
            jt.nativeSpecification = nativespec
            jt.joinFiles           = True

        # Loop over bids subject/session-directories to first get all the echo-combined deface masks
        for n, subject in enumerate(subjects, 1):

            sessions = bidscoin.lsdirs(subject, 'ses-*')
            if not sessions:
                sessions = [subject]
            for session in sessions:

                LOGGER.info('--------------------------------------')
                LOGGER.info(f"Processing ({n}/{len(subjects)}): {session}")

                datasource     = bids.DataSource(session/'dum.my')
                sub_id, ses_id = datasource.subid_sesid()

                # Read the echo-images that need to be defaced
                echofiles = sorted([match for match in session.glob(pattern) if '.nii' in match.suffixes])
                LOGGER.info(f'Loading ME-files: {echofiles}')
                echos = [nib.load(echofile) for echofile in echofiles]

                # Create a temporary echo-combined image
                tmpfile  = session/'tmp_echocombined_deface.nii'
                combined = nib.Nifti1Image(np.average([echo.get_fdata() for echo in echos]), echos[0].affine, echos[0].header)
                combined.to_filename(tmpfile)

                # Deface the echo-combined image
                LOGGER.info(f"Creating a deface-mask from the echo-combined image: {tmpfile}")
                if cluster:
                    jt.args = [str(tmpfile), '--outfile', str(tmpfile), '--force'] + [item for pair in [[f"--{key}", val] for key,val in kwargs.items()] for item in pair]
                    jt.jobName = f"pydeface_{sub_id}_{ses_id}"
                    jobid = pbatch.runJob(jt)
                    LOGGER.info(f"Your deface job has been submitted with ID: {jobid}")
                else:
                    pdu.deface_image(str(tmpfile), str(tmpfile), force=True, forcecleanup=True, **kwargs)

        if cluster:
            LOGGER.info('Waiting for the deface jobs to finish...')
            pbatch.synchronize(jobIds=[pbatch.JOB_IDS_SESSION_ALL], timeout=pbatch.TIMEOUT_WAIT_FOREVER,
                               dispose=True)
            pbatch.deleteJobTemplate(jt)

        # Loop again over bids subject/session-directories to apply the deface masks and write meta-data
        for n, subject in enumerate(subjects, 1):

            sessions = bidscoin.lsdirs(subject, 'ses-*')
            if not sessions:
                sessions = [subject]
            for session in sessions:

                LOGGER.info('--------------------------------------')
                LOGGER.info(f"Processing ({n}/{len(subjects)}): {session}")

                datasource     = bids.DataSource(session/'dum.my')
                sub_id, ses_id = datasource.subid_sesid()

                # Read the temporary defacemask and the echo-images that need to be defaced
                tmpfile    = session/'tmp_echocombined_deface.nii'
                defacemask = nib.load(tmpfile).get_fdata() != 0     # The original defacemask is saved in a temporary folder so it may be deleted -> use the defaced image to infer the mask
                tmpfile.unlink()
                for echofile in sorted([match for match in session.glob(pattern) if '.nii' in match.suffixes]):

                    # Construct the output filename and relative path name (used in BIDS)
                    echofile_rel = echofile.relative_to(session).as_posix()
                    if not output:
                        outputfile     = echofile
                        outputfile_rel = echofile_rel
                    elif output == 'derivatives':
                        outputfile     = bidsdir/'derivatives'/'deface'/sub_id/ses_id/echofile.parent.name/echofile.name
                        outputfile_rel = outputfile.relative_to(bidsdir).as_posix()
                    else:
                        outputfile     = session/output/echofile.name
                        outputfile_rel = outputfile.relative_to(session).as_posix()
                    outputfile.parent.mkdir(parents=True, exist_ok=True)

                    # Apply the defacemask
                    LOGGER.info(f'Apply deface mask on: {echofile} -> {outputfile_rel}')
                    echoimg   = nib.load(echofile)
                    outputimg = nib.Nifti1Image(echoimg.get_fdata() * defacemask, echoimg.affine, echoimg.header)
                    outputimg.to_filename(outputfile)

                    # Overwrite or add a json sidecar-file
                    inputjson  = echofile.with_suffix('').with_suffix('.json')
                    outputjson = outputfile.with_suffix('').with_suffix('.json')
                    if inputjson.is_file() and inputjson != outputjson:
                        if outputjson.is_file():
                            LOGGER.info(f"Overwriting the json sidecar-file: {outputjson}")
                            outputjson.unlink()
                        else:
                            LOGGER.info(f"Adding a json sidecar-file: {outputjson}")
                        shutil.copyfile(inputjson, outputjson)

                    # Add a custom "Defaced" field to the json sidecar-file
                    with outputjson.open('r') as output_fid:
                        data = json.load(output_fid)
                    data['Defaced'] = True
                    with outputjson.open('w') as output_fid:
                        json.dump(data, output_fid, indent=4)

                    # Update the IntendedFor fields in the fieldmap sidecar-files
                    if output and output != 'derivatives' and (session/'fmap').is_dir():
                        for fmap in (session/'fmap').glob('*.json'):
                            with fmap.open('r') as fmap_fid:
                                fmap_data = json.load(fmap_fid)
                            intendedfor = fmap_data['IntendedFor']
                            if type(intendedfor)==str:
                                intendedfor = [intendedfor]
                            if echofile_rel in intendedfor:
                                LOGGER.info(f"Updating 'IntendedFor' to {outputfile_rel} in {fmap}")
                                fmap_data['IntendedFor'] = intendedfor + [outputfile_rel]
                                with fmap.open('w') as fmap_fid:
                                    json.dump(fmap_data, fmap_fid, indent=4)

                    # Update the scans.tsv file
                    if (bidsdir/'.bidsignore').is_file():
                        bidsignore = (bidsdir/'.bidsignore').read_text().splitlines()
                    else:
                        bidsignore = [bids.unknowndatatype + '/']
                    bidsignore.append('derivatives/')
                    scans_tsv = session/f"{sub_id}{bids.add_prefix('_',ses_id)}_scans.tsv"
                    if output and output+'/' not in bidsignore and scans_tsv.is_file():
                        LOGGER.info(f"Adding {outputfile_rel} to {scans_tsv}")
                        scans_table                     = pd.read_csv(scans_tsv, sep='\t', index_col='filename')
                        scans_table.loc[outputfile_rel] = scans_table.loc[echofile_rel]
                        scans_table.sort_values(by=['acq_time','filename'], inplace=True)
                        scans_table.to_csv(scans_tsv, sep='\t', encoding='utf-8')

    LOGGER.info('-------------- FINISHED! -------------')
    LOGGER.info('')


def main():
    """Console script usage"""

    class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter): pass

    parser = argparse.ArgumentParser(formatter_class=CustomFormatter,
                                     description=__doc__,
                                     epilog='examples:\n'
                                            '  medeface /project/3017065.01/bids anat/*_T1w*\n'
                                            '  medeface /project/3017065.01/bids anat/*_T1w* -p 001 003 -o derivatives\n'
                                            '  medeface /project/3017065.01/bids anat/*_T1w* -c -n "-l walltime=00:60:00,mem=4gb"\n'
                                            '  medeface /project/3017065.01/bids anat/*_T1w* -a \'{"cost": "corratio", "verbose": ""}\'\n ')
    parser.add_argument('bidsfolder', type=str,
                        help='The bids-directory with the (multi-echo) subject data')
    parser.add_argument('pattern', type=str,
                        help="Globlike search pattern (relative to the subject/session folder) to select the images that need to be defaced, e.g. 'anat/*_T1w*'")
    parser.add_argument('-p','--participant_label', type=str, nargs='+',
                        help='Space separated list of sub-# identifiers to be processed (the sub- prefix can be left out). If not specified then all sub-folders in the bidsfolder will be processed')
    parser.add_argument('-o','--output', type=str, choices=bids.bidscoindatatypes + (bids.unknowndatatype, 'derivatives'),
                        help=f"A string that determines where the defaced images are saved. It can be the name of a BIDS datatype folder, such as 'anat', or of the derivatives folder, i.e. 'derivatives'. If output is left empty then the original images are replaced by the defaced images")
    parser.add_argument('-c','--cluster', action='store_true',
                        help='Flag to submit the deface jobs to the high-performance compute (HPC) cluster')
    parser.add_argument('-n','--nativespec', type=str, default='-l walltime=00:30:00,mem=2gb',
                        help='DRMAA native specifications for submitting deface jobs to the HPC cluster')
    parser.add_argument('-a','--args',
                        help='Additional arguments (in dict/json-style) that are passed to pydeface. See examples for usage', type=json.loads, default={})
    args = parser.parse_args()

    medeface(bidsdir    = args.bidsfolder,
             pattern    = args.pattern,
             subjects   = args.participant_label,
             output     = args.output,
             cluster    = args.cluster,
             nativespec = args.nativespec,
             kwargs     = args.args)


if __name__ == '__main__':
    LOGGER = logging.getLogger(f"bidscoin.{Path(__file__).stem}")
    main()

else:
    LOGGER = logging.getLogger(__name__)
