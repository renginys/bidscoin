Options
=======

BIDScoin has different options and settings (see below) that can be adjusted per study bidsmap or, when you want to customize the default, set as default in the `template bidsmap <bidsmap.html>`__. There are separate settings for BIDScoin and for the individual plugins that can be edited by double clicking the corresponding fields. Installed plugins can be removed or added to extend BIDScoin's functionality.

.. figure:: ./_static/bidseditor_options.png
   :scale: 75%

   The bidseditor options window with the different settings for BIDScoin and its plugins. The user can manage the plugins that will be used with the [Add] and [Remove] buttons, and save the current options to the template bidsmap by using the [Set as default] button.

BIDScoin
--------

These setting can be used by all the BIDScoin tools:

- ``version``: Used to check for version conflicts between the installed version (see ../bidscoin/version.txt) and the version that was used to create the bidsmap, or between the installed version and the latest online version.
- ``bidsignore``: Semicolon-separated list of (non-BIDS) datatypes that you want to include but that do not pass a BIDS `validation test <https://github.com/bids-standard/bids-validator#bidsignore>`__. These files are added to the `.bidsignore` file. Example: ``bidsignore: extra_data/;rTMS/;myfile.txt;yourfile.csv``
- ``subprefix``: The prefix before the subject label in the source data folder, e.g. 'patient-' if the source data is in ``raw/patient-001/ses-01/..``
- ``sesprefix``: Idem for the session label
- ``datatypes``: Datatypes that are converted to BIDS. This can be useful for ignoring / excluding specific datatypes (without changing their mappings)
- ``unknowntypes``: Datatypes that are not part of BIDS but that are converted to a BIDS-like entries in the BIDS folder
- ``ignoretypes``: Datatypes that are excluded / not converted"""

The core working of BIDScoin can be tested by clicking the [Test] button and inspection of the terminal output.

dcm2niix2bids - plugin
----------------------

The dcm2niix2bids plugin is the default bidscoiner plugin that converts DICOM and PAR/REC source data to BIDS-valid nifti- and json sidecar files. This plugin relies on `dcm2niix <https://github.com/rordenlab/dcm2niix>`__, for which you can set the following options:

- ``command``: Command to run dcm2niix from the terminal, such as:

  - ``dcm2niix`` (if the executable is already present on your path)
  - ``module add dcm2niix/v1.0.20210317; dcm2niix`` (if you use a module system)
  - ``PATH=/opt/dcm2niix/bin:$PATH; dcm2niix`` (prepend the path to your executable)
  - ``/opt/dcm2niix/bin/dcm2niix`` (specify the fullpath to the executable)
  - ``"C:\Program Files\dcm2niix\dcm2niix.exe"`` (use quotes to deal with whitespaces in your fullpath)

- ``args``: Argument string that is passed as input to dcm2niix to customize its behavior, e.g. ``-z n -i y`` for ignoring derived data and having uncompressed output data.
- ``anon``: Set this anonymization flag to 'y' to round off age and to discard acquisition date from the meta data
- ``meta``: The file extensions of the associated / equally named (meta)data sourcefiles that are copied over as BIDS (sidecar) files, such as ``['.json', '.tsv', '.tsv.gz']``. You can use this to enrich json sidecar files or add data that is not supported by this plugin. For instance, with each PET DICOM image you can put a small json file with key-value pairs that are not contained in the DICOM header (such as ``{InjectedRadioactivity: 400, InjectedMass: 10}``). NB: Data entered in the meta table of the bidseditor GUI always has priority over data in source json files, which itself has priority over dcm2niix-generated json data.

To test the proper working of dcm2niix click [Test] and see the terminal output for more helptext on its input arguments

.. tip::
   - Use the [Set as default] button to put your custom dcm2niix command in your template bidsmap so that you don't have to adjust it anymore for every new study
   - SPM users may want to use '-z n', which produces unzipped nifti's

spec2nii2bids - plugin
----------------------

The spec2nii2bids plugin is a default bidscoiner plugin that converts Twix, SPAR/SDAT and P-file spectroscopy source data to BIDS-valid nifti- and json sidecar files. This plugin relies on `spec2nii <https://github.com/wexeee/spec2nii>`__, for which you can set the following options:

- ``command``: Command to run spec2nii, such as:

  - ``dcm2niix`` (normal usage, i.e. the executable is already present on your path)
  - ``module add spec2nii; spec2nii`` (if you use a module system)
  - ``PATH=/opt/spec2nii/bin:$PATH; spec2nii`` (prepend the path to your executable)
  - ``/opt/spec2nii/bin/spec2nii`` (specify the fullpath to the executable)
  - ``"C:\Program Files\spec2nii\spec2nii.exe"`` (use quotes to deal with whitespaces in your fullpath)

- ``args``: Argument string that is passed as input to spec2nii to customize its behavior
- ``anon``: Set this anonymization flag to 'y' to round off age and to discard acquisition date from the meta data
- ``meta``: The file extensions of the associated / equally named (meta)data sourcefiles that are copied over as BIDS (sidecar) files, such as ``['.json', '.tsv', '.tsv.gz']``. You can use this to enrich json sidecar files or add data that is not supported by this plugin. NB: Data entered in the meta table of the bidseditor GUI always has priority over data in source json files, which itself has priority over dcm2niix-generated json data.
- ``multiraid``: The mapVBVD argument for selecting the multiraid Twix file to load (default = 2, i.e. 2nd file)

To test the proper working of spec2nii click [Test] and see the terminal output for more helptext on its input arguments

nibabel2bids - plugin
---------------------

The nibabel2bids plugin is an optional bidscoiner plugin that converts the wide variety of `nibabel <https://nipy.org/nibabel>`__ datatypes to BIDS-valid nifti- and json sidecar files. The following options can be set:

- ``ext``: The (nibabel) file extension of the output data, i.e. ``.nii.gz`` or ``.nii``
- ``meta``: The file extensions of the associated / equally named (meta)data sourcefiles that are copied over as BIDS (sidecar) files, such as ``['.json', '.tsv', '.tsv.gz', '.bval', '.bvec']``. You can use this to enrich json sidecar files or add data that is not supported by this plugin. For instance, in this way you can still convert a nifti dataset that was previously created with dcm2niix to BIDS. NB: Data entered in the meta table of the bidseditor GUI always has priority over data in source json files, which itself has priority over dcm2niix-generated json data.

To test the proper working of nibabel click [Test] and see the terminal output for more helptext on its input arguments

.. note::
   Typically, nibabel2bids does not produce any json sidecar files, so as a user you need to provide for that yourself. You can look up the fields required by the BIDS specification and enter that information in the meta data tables of the bidseditor or put it in json files next to your source data.
