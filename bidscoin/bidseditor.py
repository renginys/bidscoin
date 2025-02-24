#!/usr/bin/env python3
"""
This application launches a graphical user interface for editing the bidsmap that is produced by
the bidsmapper. You can edit the BIDS data types and entities until all run-items have a meaningful
and nicely readable BIDS output name. The (saved) bidsmap.yaml output file will be used by the
bidscoiner to do the conversion conversion of the source data to BIDS.

You can hoover with your mouse over items to get help text (pop-up tooltips).
"""

import sys
import argparse
import textwrap
import logging
import copy
import webbrowser
import re
import ast
from typing import Union
from pydicom import dcmread
from pathlib import Path
from functools import partial
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileSystemModel, QFileDialog, QDialogButtonBox,
                             QTreeView, QHBoxLayout, QVBoxLayout, QLabel, QDialog, QMessageBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QTextBrowser,
                             QPushButton, QComboBox, QAction)

try:
    from bidscoin import bidscoin, bids
except ImportError:
    import bidscoin, bids             # This should work if bidscoin was not pip-installed


ROW_HEIGHT       = 22
BIDSCOIN_LOGO    = Path(__file__).parent/'bidscoin_logo.png'
BIDSCOIN_ICON    = Path(__file__).parent/'bidscoin.ico'
RIGHTARROW       = Path(__file__).parent/'rightarrow.png'

MAIN_HELP_URL    = f"https://bidscoin.readthedocs.io/en/{bidscoin.version()}"
HELP_URL_DEFAULT = f"https://bids-specification.readthedocs.io/en/v{bidscoin.bidsversion()}"
HELP_URLS        = {
    'anat': f"{HELP_URL_DEFAULT}/04-modality-specific-files/01-magnetic-resonance-imaging-data.html#anatomy-imaging-data",
    'dwi' : f"{HELP_URL_DEFAULT}/04-modality-specific-files/01-magnetic-resonance-imaging-data.html#diffusion-imaging-data",
    'fmap': f"{HELP_URL_DEFAULT}/04-modality-specific-files/01-magnetic-resonance-imaging-data.html#fieldmap-data",
    'func': f"{HELP_URL_DEFAULT}/04-modality-specific-files/01-magnetic-resonance-imaging-data.html#task-including-resting-state-imaging-data",
    'perf': f"{HELP_URL_DEFAULT}/04-modality-specific-files/01-magnetic-resonance-imaging-data.html#arterial-spin-labeling-perfusion-data",
    'eeg' : f"{HELP_URL_DEFAULT}/04-modality-specific-files/03-electroencephalography.html",
    'ieeg': f"{HELP_URL_DEFAULT}/04-modality-specific-files/04-intracranial-electroencephalography.html",
    'beh' : f"{HELP_URL_DEFAULT}/04-modality-specific-files/07-behavioral-experiments.html",
    'pet' : f"{HELP_URL_DEFAULT}/04-modality-specific-files/09-positron-emission-tomography.html",
    # self.unknowndatatypes: HELP_URL_DEFAULT,
    # self.ignoredatatypes : HELP_URL_DEFAULT
}

TOOLTIP_BIDSCOIN = """BIDScoin
version:      Used to check for version conflicts 
bidsignore:   Semicolon-separated list of data types that are added to the .bidsignore file,
              e.g. extra_data/;myfile.txt;yourfile.csv
subprefix:    The subject prefix used in the source data folders (e.g. "Pt" is the subprefix if subject folders are named "Pt018", "Pt019", ...)
sesprefix:    The session prefix used in the source data folders (e.g. "M_" is the subprefix if session folders are named "M_pre", "M_post", ...)
datatypes:    Datatypes that are converted to BIDS
unknowntypes: Datatypes that are not part of BIDS but that are converted to a BIDS-like entries in the BIDS folder
ignoretypes:  Datatypes that are excluded / not converted"""

TOOLTIP_DCM2NIIX = """dcm2niix2bids
command: Command to run dcm2niix from the terminal, such as:
    dcm2niix (if the executable is already present on your path)
    module add dcm2niix/v1.0.20210317; dcm2niix (if you use a module system)
    PATH=/opt/dcm2niix/bin:$PATH; dcm2niix (prepend the path to your executable)
    /opt/dcm2niix/bin/dcm2niix (specify the fullpath to the executable)
    \"C:\\Program Files\\dcm2niix\\dcm2niix.exe" (use quotes to deal with whitespaces in your fullpath)
    
args: Argument string that is passed to dcm2niix. Click [Test] and see the terminal output for usage
    Tip: SPM users may want to use '-z n', which produces unzipped nifti's
    
anon: Set this anonymization flag to 'y' to round off age and to discard acquisition date from the meta data

meta: The file extensions of the associated / equally named (meta)data sourcefiles that are copied over as
    BIDS (sidecar) files, such as ['.json', '.tsv', '.tsv.gz']. You can use this to enrich json sidecar files,
    or add data that is not supported by this plugin"""


class MainWindow(QMainWindow):

    def __init__(self, bidsfolder: Path, input_bidsmap: dict, template_bidsmap: dict, datasaved: bool=False, reset: bool=False):

        # Set-up the main window
        if not reset:
            super().__init__()
            self.setWindowIcon(QtGui.QIcon(str(BIDSCOIN_ICON)))
            self.set_menu_statusbar()

        if not input_bidsmap:
            filename, _ = QFileDialog.getOpenFileName(None, 'Open a bidsmap file', str(bidsfolder),
                                                      'YAML Files (*.yaml *.yml);;All Files (*)')
            if filename:
                input_bidsmap, _ = bids.load_bidsmap(Path(filename))
                if input_bidsmap.get('Options'):
                    template_bidsmap['Options'] = input_bidsmap['Options']      # Always use the options of the input bidsmap
            else:
                input_bidsmap = {'Options': template_bidsmap['Options']}

        # Keep track of the EditWindow status
        self.editwindow_opened = None                           # The provenance string of the run-item that is opened in the EditWindow

        # Set the input data
        self.bidsfolder        = Path(bidsfolder)               # The folder where the bids data is / will be stored
        self.input_bidsmap     = input_bidsmap                  # The original / unedited bidsmap
        self.output_bidsmap    = copy.deepcopy(input_bidsmap)   # The edited bidsmap
        self.template_bidsmap  = template_bidsmap               # The bidsmap from which new datatype run-items are taken
        self.datasaved         = datasaved                      # True if data has been saved on disk
        self.dataformats       = [dataformat for dataformat in input_bidsmap if dataformat and dataformat not in ('Options', 'PlugIns') and bids.dir_bidsmap(input_bidsmap, dataformat)]
        self.bidscoindatatypes = input_bidsmap['Options']['bidscoin'].get('datatypes',[])
        self.unknowndatatypes  = input_bidsmap['Options']['bidscoin'].get('unknowntypes',[])
        self.ignoredatatypes   = input_bidsmap['Options']['bidscoin'].get('ignoretypes',[])

        # Set-up the tabs, add the tables and put the bidsmap data in them
        tabwidget = self.tabwidget = QtWidgets.QTabWidget()
        tabwidget.setTabPosition(QtWidgets.QTabWidget.North)
        tabwidget.setTabShape(QtWidgets.QTabWidget.Rounded)

        self.subses_table       = {}
        self.samples_table      = {}
        self.options_label      = {}
        self.options_table      = {}
        self.ordered_file_index = {}
        for dataformat in self.dataformats:
            self.set_tab_bidsmap(dataformat)
        self.set_tab_options()
        self.set_tab_filebrowser()

        self.datachanged = False        # Keep track of the bidsmap data status -> True if data has been edited. Do this after updating all the tables (which assigns datachanged = True)

        # Set-up the buttons
        buttonbox = QDialogButtonBox()
        buttonbox.setStandardButtons(QDialogButtonBox.Save | QDialogButtonBox.Reset | QDialogButtonBox.Help)
        buttonbox.button(QDialogButtonBox.Help).setToolTip('Go to the online BIDScoin documentation')
        buttonbox.button(QDialogButtonBox.Save).setToolTip('Save the bidsmap to disk if you are satisfied with all the BIDS output names')
        buttonbox.button(QDialogButtonBox.Reset).setToolTip('Reset all the Options and BIDS mappings')
        buttonbox.helpRequested.connect(self.get_help)
        buttonbox.button(QDialogButtonBox.Reset).clicked.connect(self.reset)
        buttonbox.button(QDialogButtonBox.Save).clicked.connect(self.save_bidsmap)

        # Set-up the main layout
        centralwidget = QtWidgets.QWidget()
        top_layout = QVBoxLayout(centralwidget)
        top_layout.addWidget(tabwidget)
        top_layout.addWidget(buttonbox)
        tabwidget.setCurrentIndex(0)

        self.setCentralWidget(centralwidget)

        # Center the main window to the center point of screen
        if not reset:
            self.move(QApplication.desktop().screen().rect().center() - self.rect().center())

        # Restore the samples_table stretching after the main window has been sized / current tabindex has been set (otherwise the main window can become too narrow)
        for dataformat in self.dataformats:
            header = self.samples_table[dataformat].horizontalHeader()
            header.setSectionResizeMode(1, QHeaderView.Interactive)

    def closeEvent(self, event):
        """Handle exit of the main window -> check if data has been saved"""

        if not self.datasaved or self.datachanged:
            answer = QMessageBox.question(self, 'Closing the BIDS editor', 'Do you want to save the bidsmap to disk?',
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.save_bidsmap()
            elif answer == QMessageBox.Cancel:
                if event:               # User clicked the 'X'-button or pressed alt-F4 -> drop signal
                    event.ignore()
                return
            self.datasaved   = True     # Prevent re-entering this if-statement after close() -> closeEvent()
            self.datachanged = False    # Prevent re-entering this if-statement after close() -> closeEvent()

        if event:                       # User clicked the 'X'-button or pressed alt-F4 -> normal closeEvent
            super(MainWindow, self).closeEvent(event)
        else:                           # User pressed alt-X (= menu action) -> normal close()
            self.close()
        QApplication.quit()             # TODO: Do not use class method but self.something?

    @QtCore.pyqtSlot(QtCore.QPoint)
    def show_contextmenu(self, pos):
        """Pops up a context-menu for deleting or editing the right-clicked sample in the samples_table"""

        # Get the activated row-data
        dataformat = self.tabwidget.widget(self.tabwidget.currentIndex()).objectName()
        table      = self.samples_table[dataformat]
        rowindex   = table.currentRow()
        colindex   = table.currentColumn()
        datatype   = table.item(rowindex, 2).text()
        provenance = table.item(rowindex, 5).text()

        # Pop-up the context-menu
        if colindex in (-1, 0, 4):      # User clicked the index, the edit-button or elsewhere (i.e. not on an activated widget)
            return
        menu       = QtWidgets.QMenu(self)
        delete_run = menu.addAction('Remove')
        edit_run   = menu.addAction('Edit')
        action     = menu.exec(table.viewport().mapToGlobal(pos))

        if action == delete_run:
            answer = QMessageBox.question(self, f"Remove {dataformat} mapping",
                                          f'Only delete mappings for obsolete data (unless you are an expert user). Do you really want to remove this mapping"?',
                                          QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer == QMessageBox.Yes:
                LOGGER.warning(f"Expert usage: User has removed run-item {dataformat}[{datatype}]: {provenance}")
                bids.delete_run(self.output_bidsmap, bids.find_run(self.output_bidsmap, provenance, dataformat, datatype))
                self.update_subses_samples(self.output_bidsmap)
                table.setRowCount(table.rowCount() - 1)
                self.datachanged = True

        elif action == edit_run:
            self.open_editwindow(provenance, datatype)

    def set_menu_statusbar(self):
        """Set-up the menu and statusbar"""

        # Set the menus
        menubar  = QtWidgets.QMenuBar(self)
        menufile = QtWidgets.QMenu(menubar)
        menufile.setTitle('File')
        menubar.addAction(menufile.menuAction())
        menuhelp = QtWidgets.QMenu(menubar)
        menuhelp.setTitle('Help')
        menubar.addAction(menuhelp.menuAction())
        self.setMenuBar(menubar)

        # Set the file menu actions
        actionreset = QAction(self)
        actionreset.setText('Reset')
        actionreset.setStatusTip('Reset the bidsmap')
        actionreset.setShortcut('Ctrl+R')
        actionreset.triggered.connect(self.reset)
        menufile.addAction(actionreset)

        actionsave = QAction(self)
        actionsave.setText('Open')
        actionsave.setStatusTip('Open a new bidsmap from disk')
        actionsave.setShortcut('Ctrl+O')
        actionsave.triggered.connect(self.open_bidsmap)
        menufile.addAction(actionsave)

        actionsave = QAction(self)
        actionsave.setText('Save')
        actionsave.setStatusTip('Save the bidsmap to disk')
        actionsave.setShortcut('Ctrl+S')
        actionsave.triggered.connect(self.save_bidsmap)
        menufile.addAction(actionsave)

        actionexit = QAction(self)
        actionexit.setText('Exit')
        actionexit.setStatusTip('Exit the application')
        actionexit.setShortcut('Ctrl+X')
        actionexit.triggered.connect(self.closeEvent)
        menufile.addAction(actionexit)

        # Set help menu actions
        actionhelp = QAction(self)
        actionhelp.setText('Documentation')
        actionhelp.setStatusTip('Go to the online BIDScoin documentation')
        actionhelp.setShortcut('F1')
        actionhelp.triggered.connect(self.get_help)
        menuhelp.addAction(actionhelp)

        actionbidshelp = QAction(self)
        actionbidshelp.setText('BIDS specification')
        actionbidshelp.setStatusTip('Go to the online BIDS specification documentation')
        actionbidshelp.setShortcut('F2')
        actionbidshelp.triggered.connect(self.get_bids_help)
        menuhelp.addAction(actionbidshelp)

        actionabout = QAction(self)
        actionabout.setText('About BIDScoin')
        actionabout.setStatusTip('Show information about the application')
        actionabout.triggered.connect(self.show_about)
        menuhelp.addAction(actionabout)

        # Set the statusbar
        statusbar = QtWidgets.QStatusBar(self)
        statusbar.setStatusTip('Statusbar')
        self.setStatusBar(statusbar)

    def set_tab_bidsmap(self, dataformat):
        """Set the SOURCE file sample listing tab"""

        # Set the Participant labels table
        subses_label = QLabel('Participant labels')
        subses_label.setToolTip('Subject/session mapping')

        subses_table = MyQTableWidget()
        subses_table.setToolTip(f"Use e.g. '<<filepath:/sub-(.*?)/>>' to parse the subject and (optional) session label from the pathname\n"
                                f"Use a dynamic {dataformat} attribute (e.g. '<<PatientName>>') to extract the subject and (optional) session label from the {dataformat} header")
        subses_table.setMouseTracking(True)
        subses_table.setRowCount(2)
        subses_table.setColumnCount(2)
        horizontal_header = subses_table.horizontalHeader()
        horizontal_header.setVisible(False)
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        horizontal_header.setSectionResizeMode(1, QHeaderView.Stretch)
        subses_table.cellChanged.connect(self.subsescell2bidsmap)
        self.subses_table[dataformat] = subses_table

        # Set the bidsmap table
        provenance = bids.dir_bidsmap(self.input_bidsmap, dataformat)
        ordered_file_index = {}                                         # The mapping between the ordered provenance and an increasing file-index
        num_files = 0
        for file_index, file_name in enumerate(provenance):
            ordered_file_index[file_name] = file_index
            num_files = file_index + 1

        self.ordered_file_index[dataformat] = ordered_file_index

        label = QLabel('Data samples')
        label.setToolTip('List of unique source-data samples')

        self.samples_table[dataformat] = samples_table = MyQTableWidget(minimum=False)
        samples_table.setMouseTracking(True)
        samples_table.setShowGrid(True)
        samples_table.setColumnCount(6)
        samples_table.setRowCount(num_files)
        samples_table.setHorizontalHeaderLabels(['', f'{dataformat} input', 'BIDS data type', 'BIDS output', 'Action', 'Provenance'])
        samples_table.setSortingEnabled(True)
        samples_table.sortByColumn(0, QtCore.Qt.AscendingOrder)
        samples_table.setColumnHidden(2, True)
        samples_table.setColumnHidden(5, True)
        samples_table.itemDoubleClicked.connect(self.sample_doubleclicked)
        samples_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        samples_table.customContextMenuRequested.connect(self.show_contextmenu)
        header = samples_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)                 # Temporarily set it to Stretch to have Qt set the right window width -> set to Interactive in setupUI -> not reset
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        layout = QVBoxLayout()
        layout.addWidget(subses_label)
        layout.addWidget(subses_table)
        layout.addWidget(label)
        layout.addWidget(samples_table)
        tab = QtWidgets.QWidget()
        tab.setObjectName(dataformat)                                       # NB: Serves to identify the dataformat for the tables in a tab
        tab.setLayout(layout)
        self.tabwidget.addTab(tab, f"{dataformat} mappings")
        self.tabwidget.setCurrentWidget(tab)

        self.update_subses_samples(self.output_bidsmap)

    def set_tab_options(self):
        """Set the options tab"""

        # Create the bidscoin tabel
        bidscoin_options = self.output_bidsmap['Options']['bidscoin']
        self.options_label['bidscoin'] = bidscoin_label = QLabel('BIDScoin')
        bidscoin_label.setToolTip(TOOLTIP_BIDSCOIN)
        self.options_table['bidscoin'] = bidscoin_table = MyQTableWidget()
        bidscoin_table.setRowCount(len(bidscoin_options.keys()))
        bidscoin_table.setColumnCount(3)                        # columns: [key] [value] [testbutton]
        bidscoin_table.setToolTip(TOOLTIP_BIDSCOIN)
        horizontal_header = bidscoin_table.horizontalHeader()
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        horizontal_header.setSectionResizeMode(1, QHeaderView.Stretch)
        horizontal_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        horizontal_header.setVisible(False)
        test_button = QPushButton('Test')                       # Add a test-button
        test_button.clicked.connect(self.test_bidscoin)
        test_button.setToolTip(f'Click to test the BIDScoin installation')
        bidscoin_table.setCellWidget(0, 2, test_button)
        for n, (key, value) in enumerate(bidscoin_options.items()):
            bidscoin_table.setItem(n, 0, MyWidgetItem(key, iseditable=False))
            bidscoin_table.setItem(n, 1, MyWidgetItem(value))
        bidscoin_table.cellChanged.connect(self.options2bidsmap)

        # Set-up the tab layout and add the bidscoin table
        layout = self.options_layout = QVBoxLayout()
        layout.addWidget(bidscoin_label)
        layout.addWidget(bidscoin_table)

        # Add the plugin tabels
        for plugin, options in self.output_bidsmap['Options']['plugins'].items():
            plugin_label, plugin_table = self.plugin_table(plugin, options)
            layout.addWidget(plugin_label)
            layout.addWidget(plugin_table)

        # Add an 'Add' button below the tables at the right side
        add_button = QPushButton('Add')
        add_button.clicked.connect(self.add_plugin)
        add_button.setToolTip(f'Click to add an installed plugin')
        layout.addWidget(add_button, alignment=QtCore.Qt.AlignRight)

        # Add an 'Default' button below the tables at the left side
        set_button = QPushButton('Set as default')
        set_button.clicked.connect(self.save_options)
        set_button.setToolTip(f'Click to store these options in your default template bidsmap, i.e. set them as default for all new studies')
        layout.addStretch()
        layout.addWidget(set_button, alignment=QtCore.Qt.AlignLeft)

        tab = QtWidgets.QWidget()
        tab.setLayout(layout)

        self.tabwidget.addTab(tab, 'Options')

    def set_tab_filebrowser(self):
        """Set the raw data folder inspector tab"""

        rootfolder = str(self.bidsfolder.parent)
        label = QLabel(rootfolder)
        label.setWordWrap(True)

        model = self.model = QFileSystemModel()
        model.setRootPath(rootfolder)
        model.setFilter(QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllDirs | QtCore.QDir.Files)
        tree = QTreeView()
        tree.setModel(model)
        tree.setRootIndex(model.index(rootfolder))
        tree.setAnimated(False)
        tree.setSortingEnabled(True)
        tree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        tree.setExpanded(model.index(str(self.bidsfolder)), True)
        tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setStretchLastSection(False)
        tree.doubleClicked.connect(self.open_inspectwindow)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(tree)
        tab = QtWidgets.QWidget()
        tab.setLayout(layout)

        self.tabwidget.addTab(tab, 'Data browser')

    def update_subses_samples(self, output_bidsmap):
        """(Re)populates the sample list with bidsnames according to the bidsmap"""

        self.datachanged = True

        dataformat = self.tabwidget.widget(self.tabwidget.currentIndex()).objectName()

        self.output_bidsmap = output_bidsmap  # input main window / output from edit window -> output main window

        # Update the subject / session table
        subitem = MyWidgetItem('subject', iseditable=False)
        subitem.setToolTip(bids.get_entityhelp('sub'))
        sesitem = MyWidgetItem('session', iseditable=False)
        sesitem.setToolTip(bids.get_entityhelp('ses'))
        subses_table = self.subses_table[dataformat]
        subses_table.setItem(0, 0, subitem)
        subses_table.setItem(1, 0, sesitem)
        subses_table.setItem(0, 1, MyWidgetItem(output_bidsmap[dataformat]['subject']))
        subses_table.setItem(1, 1, MyWidgetItem(output_bidsmap[dataformat]['session']))

        # Update the run samples table
        idx = 0
        samples_table = self.samples_table[dataformat]
        samples_table.blockSignals(True)
        samples_table.setSortingEnabled(False)
        samples_table.clearContents()
        for datatype in self.bidscoindatatypes + self.unknowndatatypes + self.ignoredatatypes:
            runs = output_bidsmap.get(dataformat, {}).get(datatype, [])

            if not runs: continue
            for run in runs:

                # Check the run
                loglevel = LOGGER.level
                LOGGER.setLevel('ERROR')
                validrun = bids.check_run(datatype, run, validate=False)
                LOGGER.setLevel(loglevel)

                provenance   = Path(run['provenance'])
                subid        = output_bidsmap[dataformat]['subject']
                sesid        = output_bidsmap[dataformat]['session']
                subid, sesid = run['datasource'].subid_sesid(subid, sesid if sesid else '')
                bidsname     = bids.get_bidsname(subid, sesid, run)
                if run['bids'].get('suffix') in bids.get_derivatives(datatype):
                    session  = self.bidsfolder/'derivatives'/'[manufacturer]'/subid/sesid
                else:
                    session  = self.bidsfolder/subid/sesid
                row_index    = self.ordered_file_index[dataformat][provenance]

                samples_table.setItem(idx, 0, MyWidgetItem(f"{row_index+1:03d}", iseditable=False))
                samples_table.setItem(idx, 1, MyWidgetItem(provenance.name))
                samples_table.setItem(idx, 2, MyWidgetItem(datatype))                           # Hidden column
                samples_table.setItem(idx, 3, MyWidgetItem(Path(datatype)/(bidsname + '.*')))
                samples_table.setItem(idx, 5, MyWidgetItem(provenance))                         # Hidden column

                samples_table.item(idx, 0).setFlags(QtCore.Qt.NoItemFlags)
                samples_table.item(idx, 1).setFlags(QtCore.Qt.ItemIsEnabled)
                samples_table.item(idx, 2).setFlags(QtCore.Qt.ItemIsEnabled)
                samples_table.item(idx, 3).setFlags(QtCore.Qt.ItemIsEnabled)
                samples_table.item(idx, 1).setToolTip('Double-click to inspect the header information')
                samples_table.item(idx, 1).setStatusTip(str(provenance.parent) + str(Path('/')))
                samples_table.item(idx, 3).setStatusTip(str(session) + str(Path('/')))

                if samples_table.item(idx, 3):
                    if not validrun or datatype in self.unknowndatatypes:
                        samples_table.item(idx, 3).setForeground(QtGui.QColor('red'))
                        samples_table.item(idx, 3).setToolTip(f"Red: This {datatype} item is not BIDS-valid but will still be converted. You should edit this item or make sure it is in your bidsignore list ([Options] tab)")
                    elif datatype in self.ignoredatatypes:
                        samples_table.item(idx, 1).setForeground(QtGui.QColor('gray'))
                        samples_table.item(idx, 3).setForeground(QtGui.QColor('gray'))
                        f = samples_table.item(idx, 3).font()
                        f.setStrikeOut(True)
                        samples_table.item(idx, 3).setFont(f)
                        samples_table.item(idx, 3).setToolTip('Gray / Strike-out: This imaging data type will be ignored and not converted BIDS')
                    else:
                        samples_table.item(idx, 3).setForeground(QtGui.QColor('green'))
                        samples_table.item(idx, 3).setToolTip(f"Green: This '{datatype}' data type is part of BIDS")

                if validrun:
                    edit_button = QPushButton('Edit')
                    edit_button.setToolTip('Click to see more details and edit the BIDS output name')
                else:
                    edit_button = QPushButton('Edit*')
                    edit_button.setToolTip('*: Contains invalid / missing values! Click to see more details and edit the BIDS output name')
                edit_button.clicked.connect(self.open_editwindow)
                edit_button.setCheckable(not sys.platform.startswith('darwin'))
                edit_button.setAutoExclusive(True)
                if provenance.name and str(provenance) == self.editwindow_opened:   # Highlight the previously opened item
                    edit_button.setChecked(True)
                else:
                    edit_button.setChecked(False)
                samples_table.setCellWidget(idx, 4, edit_button)

                idx += 1

        samples_table.setSortingEnabled(True)
        samples_table.blockSignals(False)

    def subsescell2bidsmap(self, rowindex: int, colindex:int):
        """Subject or session value has been changed in subject-session table"""

        # Only if cell was actually clicked, update
        if colindex == 1:
            dataformat = self.tabwidget.widget(self.tabwidget.currentIndex()).objectName()
            key        = self.subses_table[dataformat].item(rowindex, 0).text().strip()
            value      = self.subses_table[dataformat].item(rowindex, 1).text().strip()
            oldvalue   = self.output_bidsmap[dataformat][key]
            if oldvalue is None:
                oldvalue = ''

            # Only if cell content was changed, update
            if key and value != oldvalue:
                if key == 'subject':
                    LOGGER.warning(f"Expert usage: User has set {dataformat}['{key}'] from '{oldvalue}' to '{value}'")
                else:
                    LOGGER.info(f"User has set {dataformat}['{key}'] from '{oldvalue}' to '{value}'")
                self.output_bidsmap[dataformat][key] = value
                self.update_subses_samples(self.output_bidsmap)

    def open_editwindow(self, provenance: Path=Path(), datatype: str= ''):
        """Make sure that index map has been updated"""

        dataformat = self.tabwidget.widget(self.tabwidget.currentIndex()).objectName()
        if not datatype:
            samples_table = self.samples_table[dataformat]
            clicked       = self.focusWidget()
            rowindex      = samples_table.indexAt(clicked.pos()).row()
            datatype      = samples_table.item(rowindex, 2).text()
            provenance    = samples_table.item(rowindex, 5).text()

        # Check for open edit window, find the right datatype index and open the edit window
        if not self.editwindow_opened:
            # Find the source index of the run in the list of runs (using the provenance) and open the edit window
            for run in self.output_bidsmap[dataformat][datatype]:
                if Path(run['provenance']) == Path(provenance):
                    LOGGER.info(f'User is editing {provenance}')
                    self.editwindow        = EditWindow(run, self.output_bidsmap, self.template_bidsmap)
                    self.editwindow_opened = str(provenance)
                    self.editwindow.done_edit.connect(self.update_subses_samples)
                    self.editwindow.finished.connect(self.release_editwindow)
                    self.editwindow.show()
                    return
            LOGGER.error(f"Could not find {provenance} run-item")

        else:
            # Ask the user if he wants to save his results first before opening a new edit window
            self.editwindow.reject()
            if self.editwindow_opened:
                return
            self.open_editwindow(provenance, datatype)

    def release_editwindow(self):
        """Allow a new edit window to be opened"""
        self.editwindow_opened = None

    def plugin_table(self, plugin: str, options: dict) -> tuple:
        """:return: a plugin-label and a filled plugin-table"""

        self.options_label[plugin] = plugin_label = QLabel(f"{plugin} - plugin")
        self.options_table[plugin] = plugin_table = MyQTableWidget()
        plugin_table.setRowCount(max(len(options.keys()) + 1, 2))           # Add an extra row for new key-value pairs
        plugin_table.setColumnCount(3)                                      # columns: [key] [value] [testbutton]
        horizontal_header = plugin_table.horizontalHeader()
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        horizontal_header.setSectionResizeMode(1, QHeaderView.Stretch)
        horizontal_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        horizontal_header.setVisible(False)
        test_button = QPushButton('Test')                                   # Add a test-button
        test_button.clicked.connect(partial(self.test_plugin, plugin))
        test_button.setToolTip(f'Click to test the "{plugin}" installation')
        plugin_table.setCellWidget(0, 2, test_button)
        delete_button = QPushButton('Remove')                               # Add a delete-button
        delete_button.clicked.connect(partial(self.del_plugin, plugin))
        delete_button.setToolTip(f'Click to discard / stop using the "{plugin}" plugin')
        plugin_table.setCellWidget(1, 2, delete_button)
        if plugin == 'dcm2niix2bids':
            tooltip = TOOLTIP_DCM2NIIX
        else:
            tooltip = f"Here you can enter key-value data for the '{plugin}' plugin"
        plugin_label.setToolTip(tooltip)
        plugin_table.setToolTip(tooltip)
        for n, (key, value) in enumerate(options.items()):
            plugin_table.setItem(n, 0, MyWidgetItem(key))
            plugin_table.setItem(n, 1, MyWidgetItem(value))
            plugin_table.setItem(n, 2, MyWidgetItem('', iseditable=False))
        plugin_table.setItem(plugin_table.rowCount() - 1, 2, MyWidgetItem('', iseditable=False))
        plugin_table.cellChanged.connect(self.options2bidsmap)

        return plugin_label, plugin_table

    def options2bidsmap(self, rowindex: int, colindex: int):
        """Saves all Options tables to the bidsmap and add an extra row to the plugin_table if it is full"""

        for plugin,table in self.options_table.items():
            if plugin == 'bidscoin':
                oldoptions = self.output_bidsmap['Options']['bidscoin']
            else:
                oldoptions = self.output_bidsmap['Options']['plugins'].get(plugin,{})
            newoptions = {}
            for rownr in range(table.rowCount()):
                keyitem = table.item(rownr, 0)
                valitem = table.item(rownr, 1)
                key = val = ''
                if keyitem: key = keyitem.text().strip()
                if valitem: val = valitem.text().strip()
                if key:
                    try: val = ast.literal_eval(val)            # Converting string to list
                    except (ValueError, SyntaxError): pass
                    newoptions[key] = val
                    if val != oldoptions.get(key):
                        LOGGER.info(f"User has set the '{plugin}' option from '{key}: {oldoptions.get(key)}' to '{key}: {val}'")
                        self.datachanged = True
            if plugin == 'bidscoin':
                self.output_bidsmap['Options']['bidscoin'] = newoptions
            else:
                self.output_bidsmap['Options']['plugins'][plugin] = newoptions

            # Add an extra row if the table if full
            if rowindex + 1 == table.rowCount() and table.currentItem() and table.currentItem().text().strip():
                table.blockSignals(True)
                table.insertRow(table.rowCount())
                table.setItem(table.rowCount() - 1, 2, MyWidgetItem('', iseditable=False))
                table.blockSignals(False)

    def add_plugin(self):
        """Interactively add an installed plugin to the Options-tab and save the data in the bidsmap"""

        # Set-up a plugin dropdown menu
        label    = QLabel('Select a plugin that you would like to add')
        plugins  = bidscoin.list_plugins()
        dropdown = QComboBox()
        dropdown.addItems([plugin.stem for plugin in plugins])

        # Set-up OK/Cancel buttons
        buttonbox = QDialogButtonBox()
        buttonbox.setStandardButtons(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttonbox.button(QDialogButtonBox.Ok).setToolTip('Adds the selected plugin to the bidsmap options')

        # Set-up the dialog window and wait till the user has selected a plugin
        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(dropdown)
        layout.addWidget(buttonbox)
        qdialog = QDialog(modal=True)
        qdialog.setLayout(layout)
        qdialog.setWindowTitle('BIDScoin Options')
        qdialog.setWindowIcon(QtGui.QIcon(str(BIDSCOIN_ICON)))
        buttonbox.accepted.connect(qdialog.accept)
        buttonbox.rejected.connect(qdialog.reject)
        answer = qdialog.exec()
        if not answer:
            return

        # Check the selected plugin and get it's options
        plugin = dropdown.currentText()
        if plugin in self.output_bidsmap['Options']['plugins']:
            LOGGER.error(f"Cannot add the '{plugin}' plugin as it already exists in the bidsmap")
            return
        module  = bidscoin.import_plugin(plugin)
        options = self.input_bidsmap[   'Options']['plugins'].get(plugin,
                  self.template_bidsmap['Options']['plugins'].get(plugin,
                  module.OPTIONS if 'OPTIONS' in dir(module) else {}))

        # Insert the selected plugin in the options_layout
        LOGGER.info(f"Adding the '{plugin}' plugin to bidsmap")
        plugin_label, plugin_table = self.plugin_table(plugin, options)
        self.options_layout.insertWidget(self.options_layout.count()-3, plugin_label)
        self.options_layout.insertWidget(self.options_layout.count()-3, plugin_table)
        self.output_bidsmap['Options']['plugins'][plugin] = options
        self.datachanged = True

    def del_plugin(self, plugin: str):
        """Removes the plugin table from the Options-tab and the data from the bidsmap"""

        LOGGER.info(f"Removing the '{plugin}' from bidsmap['Options']['plugins']")
        plugin_label = self.options_label[plugin]
        plugin_table = self.options_table[plugin]
        self.options_layout.removeWidget(plugin_label)
        self.options_layout.removeWidget(plugin_table)
        plugin_label.deleteLater()
        plugin_table.deleteLater()
        self.options_label.pop(plugin, None)
        self.options_table.pop(plugin, None)
        self.output_bidsmap['Options']['plugins'].pop(plugin, None)
        self.datachanged = True

    def test_plugin(self, plugin: str):
        """Test the plugin and show the result in a pop-up window"""

        if bidscoin.test_plugin(Path(plugin), self.output_bidsmap['Options']['plugins'].get(plugin,{})):
            QMessageBox.information(self, 'Plugin test', f"Import of {plugin}: Passed\nSee terminal output for more info")
        else:
            QMessageBox.warning(self, 'Plugin test', f"Import of {plugin}: Failed\nSee terminal output for more info")

    def test_bidscoin(self):
        """Test the bidsmap tool and show the result in a pop-up window"""

        if bidscoin.test_bidscoin(self.input_bidsmap, options=self.output_bidsmap['Options'], testplugins=False):
            QMessageBox.information(self, 'Tool test', f"BIDScoin test: Passed\nSee terminal output for more info")
        else:
            QMessageBox.warning(self, 'Tool test', f"BIDScoin test: Failed\nSee terminal output for more info")

    def reset(self):
        """Reset button: reset the window with the original input BIDS map"""

        if self.editwindow_opened:
            self.editwindow.reject(confirm=False)

        LOGGER.info('User resets the bidsmap')
        self.__init__(self.bidsfolder,
                      self.input_bidsmap,
                      self.template_bidsmap,
                      self.datasaved,
                      reset=True)

        # Start with a fresh errorlog
        for filehandler in LOGGER.handlers:
            if filehandler.name=='errorhandler' and Path(filehandler.baseFilename).stat().st_size:
                errorfile = filehandler.baseFilename
                LOGGER.info(f"Resetting {errorfile}")
                with open(errorfile, 'w'):          # TODO: This works but it is a hack that somehow prefixes a lot of whitespace to the first LOGGER call
                    pass

    def open_bidsmap(self):
        """Load a bidsmap from disk and open it the main window"""

        if not self.datasaved or self.datachanged:
            answer = QMessageBox.question(self, 'Opening a new bidsmap', 'Do you want to save the current bidsmap to disk?',
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.save_bidsmap()
            elif answer == QMessageBox.Cancel:
                return

        filename, _ = QFileDialog.getOpenFileName(self, 'Open File', str(self.bidsfolder/'code'/'bidscoin'/'bidsmap.yaml'), 'YAML Files (*.yaml *.yml);;All Files (*)')
        if filename:
            QtCore.QCoreApplication.setApplicationName(f"{filename} - BIDS editor")
            self.input_bidsmap, _ = bids.load_bidsmap(Path(filename))
            self.reset()

    def save_bidsmap(self):
        """Check and save the bidsmap to file"""

        for dataformat in self.dataformats:
            if self.output_bidsmap[dataformat].get('fmap'):
                for run in self.output_bidsmap[dataformat]['fmap']:
                    if not (run['meta'].get('B0FieldSource') or run['meta'].get('B0FieldIdentifier') or run['meta'].get('IntendedFor')):
                        LOGGER.warning(f"B0FieldIdentifier/IntendedFor fieldmap value is empty for {dataformat} run-item: {run['provenance']}")

        filename,_ = QFileDialog.getSaveFileName(self, 'Save File',  str(self.bidsfolder/'code'/'bidscoin'/'bidsmap.yaml'), 'YAML Files (*.yaml *.yml);;All Files (*)')
        if filename:
            bids.save_bidsmap(Path(filename), self.output_bidsmap)
            QtCore.QCoreApplication.setApplicationName(f"{filename} - BIDS editor")
            self.datasaved   = True
            self.datachanged = False

    def save_options(self):
        """Export the options to a template bidsmap on disk"""

        yamlfile, _ = QFileDialog.getOpenFileName(self, 'Select the (default) template bidsmap to save the options in',
                        str(bidscoin.bidsmap_template), 'YAML Files (*.yaml *.yml);;All Files (*)')
        if yamlfile:
            LOGGER.info(f"Saving bidsmap['Options'] in: {yamlfile}")
            with open(yamlfile, 'r') as stream:
                bidsmap = bids.yaml.load(stream)
            bidsmap['Options'] = self.output_bidsmap['Options']
            with open(yamlfile, 'w') as stream:
                bids.yaml.dump(bidsmap, stream)

    def sample_doubleclicked(self, item):
        """When source file is double clicked in the samples_table, show the inspect or edit window"""

        dataformat = self.tabwidget.widget(self.tabwidget.currentIndex()).objectName()
        datatype   = self.samples_table[dataformat].item(item.row(), 2).text()
        sourcefile = self.samples_table[dataformat].item(item.row(), 5).text()
        if item.column() == 1:
            self.popup = InspectWindow(Path(sourcefile))
            self.popup.show()
            self.popup.scrollbar.setValue(0)  # This can only be done after self.popup.show()
        if item.column() == 3:
            self.open_editwindow(sourcefile, datatype)

    def open_inspectwindow(self, index: int):
        """Opens the inspect or native application window when a data file in the file-tree tab is double-clicked"""

        datafile = Path(self.model.fileInfo(index).absoluteFilePath())
        if bids.is_dicomfile(datafile) or bids.is_parfile(datafile):
            self.popup = InspectWindow(datafile)
            self.popup.show()
            self.popup.scrollbar.setValue(0)  # This can only be done after self.popup.show()
        elif datafile.is_file():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(datafile)))

    def show_about(self):
        """Shows a pop-up window with the BIDScoin version"""

        version, message = bidscoin.version(check=True)
        # QMessageBox.about(self, 'About', f"BIDS editor {version}\n\n{message}")    # Has an ugly / small icon image
        messagebox = QMessageBox(self)
        messagebox.setText(f"\n\nBIDS editor {version}\n\n{message}")
        messagebox.setWindowTitle('About')
        messagebox.setIconPixmap(QtGui.QPixmap(str(BIDSCOIN_LOGO)).scaled(150, 150, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        messagebox.show()

    @staticmethod
    def get_help():
        """Get online help. """
        webbrowser.open(MAIN_HELP_URL)

    @staticmethod
    def get_bids_help():
        """Get online help. """
        webbrowser.open(HELP_URL_DEFAULT)


class EditWindow(QDialog):
    """
    EditWindow().result() == 1: done with result, i.e. done_edit -> new bidsmap
    EditWindow().result() == 2: done without result
    """

    # Emit the new bidsmap when done (see docstring)
    done_edit = QtCore.pyqtSignal(dict)

    def __init__(self, run, bidsmap: dict, template_bidsmap: dict):
        super().__init__()
        # Set the data
        datasource: bids.DataSource = run['datasource']
        self.datasource        = datasource
        self.dataformat        = datasource.dataformat  # The data format of the run-item being edited (bidsmap[dataformat][datatype][run-item])
        self.source_datatype   = datasource.datatype    # The BIDS datatype of the original run-item
        self.target_datatype   = datasource.datatype    # The BIDS datatype that the edited run-item is being changed into
        self.current_datatype  = datasource.datatype    # The BIDS datatype of the run-item just before it is being changed (again)
        self.bidscoindatatypes = [datatype for datatype in bidsmap['Options']['bidscoin'].get('datatypes',[])    if datatype in template_bidsmap[self.dataformat]]
        self.unknowndatatypes  = [datatype for datatype in bidsmap['Options']['bidscoin'].get('unknowntypes',[]) if datatype in template_bidsmap[self.dataformat]]
        self.ignoredatatypes   = [datatype for datatype in bidsmap['Options']['bidscoin'].get('ignoretypes',[])  if datatype in template_bidsmap[self.dataformat]]
        self.source_bidsmap    = bidsmap                # The bidsmap at the start of the edit = output_bidsmap in the MainWindow
        self.target_bidsmap    = copy.deepcopy(bidsmap) # The edited bidsmap -> will be returned as output_bidsmap in the MainWindow
        self.template_bidsmap  = template_bidsmap       # The bidsmap from which new datatype run-items are taken
        self.source_run        = run                    # The original run-item from the source bidsmap
        self.target_run        = copy.deepcopy(run)     # The edited run-item that is inserted in the target_bidsmap
        self.get_allowed_suffixes()                     # Set the possible suffixes the user can select for a given datatype
        subid                  = bidsmap[self.dataformat]['subject']
        sesid                  = bidsmap[self.dataformat]['session']
        self.subid, self.sesid = datasource.subid_sesid(subid, sesid if sesid else '')

        # Set-up the window
        self.setWindowIcon(QtGui.QIcon(str(BIDSCOIN_ICON)))
        self.setWindowFlags(self.windowFlags() & QtCore.Qt.WindowTitleHint & QtCore.Qt.WindowMinMaxButtonsHint & QtCore.Qt.WindowCloseButtonHint)
        self.setWindowTitle('Edit BIDS mapping')
        self.setWhatsThis(f"BIDScoin mapping of {self.dataformat} properties and attributes to BIDS output data")

        # Get data for the tables
        data_properties, data_attributes, data_bids, data_meta = self.run2data()

        # Set-up the properties table
        self.properties_label = QLabel('Properties')
        self.properties_label.setToolTip(f"The filesystem properties that match with (identify) the source file. NB: Expert usage (e.g. using regular expressions, see documentation). Copy: Ctrl+C")
        self.properties_table = self.set_table(data_properties, 'properties')
        self.properties_table.cellChanged.connect(self.propertiescell2run)
        self.properties_table.setToolTip(f"The filesystem property that matches with the source file")
        self.properties_table.cellDoubleClicked.connect(self.inspect_sourcefile)

        # Set-up the attributes table
        self.attributes_label = QLabel(f"Attributes")
        self.attributes_label.setToolTip(f"The {self.dataformat} attributes that match with (identify) the source file. NB: Expert usage (e.g. using regular expressions, see documentation). Copy: Ctrl+C")
        self.attributes_table = self.set_table(data_attributes, 'attributes', minimum=False)
        self.attributes_table.cellChanged.connect(self.attributescell2run)
        self.attributes_table.setToolTip(f"The {self.dataformat} attribute that matches with the source file")

        # Set-up the datatype dropdown menu
        self.datatype_label = QLabel('Data type')
        self.datatype_label.setToolTip(f"The BIDS data type and entities for constructing the BIDS output filename. You are encouraged to change their default values to be more meaningful and readable")
        self.datatype_dropdown = QComboBox()
        self.datatype_dropdown.addItems(self.bidscoindatatypes + self.unknowndatatypes + self.ignoredatatypes)
        self.datatype_dropdown.setCurrentIndex(self.datatype_dropdown.findText(self.target_datatype))
        self.datatype_dropdown.currentIndexChanged.connect(self.datatype_dropdown_change)
        self.datatype_dropdown.setToolTip('The BIDS data type. First make sure this one is correct, then choose the right suffix')
        for n, datatype in enumerate(self.bidscoindatatypes):
            self.datatype_dropdown.setItemData(n, bids.get_datatypehelp(datatype), QtCore.Qt.ToolTipRole)

        # Set-up the BIDS table
        self.bids_label = QLabel('Entities')
        self.bids_label.setToolTip(f"The BIDS entities that are used to construct the BIDS output filename. You are encouraged to change their default values to be more meaningful and readable")
        self.bids_table = self.set_table(data_bids, 'bids')
        self.bids_table.setToolTip(f"The BIDS entity that is used to construct the BIDS output filename. You are encouraged to change its default value to be more meaningful and readable")
        self.bids_table.cellChanged.connect(self.bidscell2run)

        # Set-up the meta table
        self.meta_label = QLabel('Meta data')
        self.meta_label.setToolTip(f"Key-value pairs that will be appended to the (e.g. dcm2niix-produced) json sidecar file")
        self.meta_table = self.set_table(data_meta, 'meta', minimum=False)
        self.meta_table.setShowGrid(True)
        self.meta_table.cellChanged.connect(self.metacell2run)
        self.meta_table.setToolTip(f"The key-value pair that will be appended to the (e.g. dcm2niix-produced) json sidecar file")

        # Set-up non-editable BIDS output name section
        self.bidsname_label = QLabel('Data filename')
        self.bidsname_label.setToolTip(f"Preview of the BIDS output name for this data type")
        self.bidsname_textbox = QTextBrowser()
        self.bidsname_textbox.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.bidsname_textbox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.bidsname_textbox.setMinimumHeight(ROW_HEIGHT + 2)
        self.refresh_bidsname()

        # Group the tables in boxes
        sizepolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        sizepolicy.setHorizontalStretch(1)

        groupbox1 = QGroupBox(self.dataformat + ' input')
        groupbox1.setSizePolicy(sizepolicy)
        layout1 = QVBoxLayout()
        layout1.addWidget(self.properties_label)
        layout1.addWidget(self.properties_table)
        layout1.addWidget(self.attributes_label)
        layout1.addWidget(self.attributes_table)
        groupbox1.setLayout(layout1)

        groupbox2 = QGroupBox('BIDS output')
        groupbox2.setSizePolicy(sizepolicy)
        layout2 = QVBoxLayout()
        layout2.addWidget(self.datatype_label)
        layout2.addWidget(self.datatype_dropdown, alignment=QtCore.Qt.AlignLeft)
        # layout2.addWidget(self.bids_label)
        layout2.addWidget(self.bids_table)
        layout2.addWidget(self.bidsname_label)
        layout2.addWidget(self.bidsname_textbox)
        layout2.addWidget(self.meta_label)
        layout2.addWidget(self.meta_table)
        groupbox2.setLayout(layout2)

        # Add a box1 -> box2 arrow
        arrow = QLabel()
        arrow.setPixmap(QtGui.QPixmap(str(RIGHTARROW)).scaled(30, 30, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

        # Add the boxes to the layout
        layout_tables = QHBoxLayout()
        layout_tables.addWidget(groupbox1)
        layout_tables.addWidget(arrow)
        layout_tables.addWidget(groupbox2)

        # Set-up buttons
        buttonbox    = QDialogButtonBox()
        exportbutton = buttonbox.addButton('Export', QDialogButtonBox.ActionRole)
        exportbutton.setIcon(QtGui.QIcon.fromTheme('document-save'))
        exportbutton.setToolTip('Export this run item to an existing (template) bidsmap')
        exportbutton.clicked.connect(self.export_run)
        buttonbox.setStandardButtons(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset | QDialogButtonBox.Help)
        buttonbox.button(QDialogButtonBox.Reset).setToolTip('Reset the edits you made')
        buttonbox.button(QDialogButtonBox.Ok).setToolTip('Apply the edits you made and close this window')
        buttonbox.button(QDialogButtonBox.Cancel).setToolTip('Discard the edits you made and close this window')
        buttonbox.button(QDialogButtonBox.Help).setToolTip('Go to the online BIDS specification for more info')
        buttonbox.accepted.connect(self.accept_run)
        buttonbox.rejected.connect(partial(self.reject, False))
        buttonbox.helpRequested.connect(self.get_help)
        buttonbox.button(QDialogButtonBox.Reset).clicked.connect(self.reset)

        # Set-up the main layout
        layout_main = QVBoxLayout(self)
        layout_main.addLayout(layout_tables)
        layout_main.addWidget(buttonbox)

    def reject(self, confirm=True):
        """Ask if the user really wants to close the window"""

        if confirm and re.sub('<(?!.*<).*? object at .*?>','',str(self.target_run)) != re.sub('<(?!.*<).*? object at .*?>','',str(self.source_run)):    # Ignore the memory address of the datasource object
            self.raise_()
            answer = QMessageBox.question(self, 'Edit BIDS mapping', 'Closing window, do you want to save the changes you made?',
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.accept_run()
                return
            if answer == QMessageBox.No:
                self.done(2)
                LOGGER.info(f'User has discarded the edit')
                return
            if answer == QMessageBox.Cancel:
                return

        LOGGER.info(f'User has canceled the edit')

        super(EditWindow, self).reject()

    def get_allowed_suffixes(self):
        """Derive the possible suffixes for each datatype from the template. """

        allowed_suffixes = {}
        for datatype in self.bidscoindatatypes + self.unknowndatatypes + self.ignoredatatypes:
            allowed_suffixes[datatype] = []
            runs = self.template_bidsmap.get(self.dataformat, {}).get(datatype, [])
            if not runs: continue
            for run in runs:
                suffix = run['bids'].get('suffix')
                if suffix and suffix not in allowed_suffixes.get(datatype, []):
                    allowed_suffixes[datatype].append(suffix)

        self.allowed_suffixes = allowed_suffixes

    def run2data(self) -> tuple:
        """Derive the tabular data from the target_run, needed to render the edit window
        :return: (data_properties, data_attributes, data_bids, data_meta)
        """

        run      = self.target_run
        filepath = self.datasource.properties('filepath')
        filename = self.datasource.properties('filename')
        filesize = self.datasource.properties('filesize')
        nrfiles  = self.datasource.properties('nrfiles')
        data_properties = [[{'value': 'filepath',                        'iseditable': False},
                            {'value': run['properties'].get('filepath'), 'iseditable': True},
                            {'value': filepath,                          'iseditable': False}],
                           [{'value': 'filename',                        'iseditable': False},
                            {'value': run['properties'].get('filename'), 'iseditable': True},
                            {'value': filename,                          'iseditable': False}],
                           [{'value': 'filesize',                        'iseditable': False},
                            {'value': run['properties'].get('filesize'), 'iseditable': True},
                            {'value': filesize,                          'iseditable': False}],
                           [{'value': 'nrfiles',                         'iseditable': False},
                            {'value': run['properties'].get('nrfiles'),  'iseditable': True},
                            {'value': nrfiles,                           'iseditable': False}]]

        data_attributes = []
        for key, value in run['attributes'].items():
            data_attributes.append([{'value': key,   'iseditable': False},
                                    {'value': value, 'iseditable': True}])

        data_bids = []
        for key in [bids.entities[entity]['entity'] for entity in bids.entitiesorder if entity not in ('subject','session')] + ['suffix']:   # Impose the BIDS-specified order + suffix
            if key in run['bids']:
                value = run['bids'].get(key)
                if (self.target_datatype in self.bidscoindatatypes and key=='suffix') or isinstance(value, list):
                    iseditable = False
                else:
                    iseditable = True
                data_bids.append([{'value': key,   'iseditable': False},
                                  {'value': value, 'iseditable': iseditable}])          # NB: This can be a (menu) list

        data_meta = []
        for key, value in run['meta'].items():
            data_meta.append([{'value': key,   'iseditable': True},
                              {'value': value, 'iseditable': True}])

        return data_properties, data_attributes, data_bids, data_meta

    def set_table(self, data: list, name: str, minimum: bool=True) -> QTableWidget:
        """Return a table widget filled with the data"""

        if data:
            nrcolumns = len(data[0])
        else:
            nrcolumns = 2                               # Always at least two columns (i.e. key, value)
        table = MyQTableWidget(minimum=minimum)
        table.setColumnCount(nrcolumns)
        table.setObjectName(name)                       # NB: Serves to identify the tables in fill_table()
        table.setHorizontalHeaderLabels(('key', 'value'))
        horizontal_header = table.horizontalHeader()
        horizontal_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        horizontal_header.setSectionResizeMode(nrcolumns-1, QHeaderView.Stretch)
        horizontal_header.setVisible(False)

        self.fill_table(table, data)

        return table

    def fill_table(self, table: QTableWidget, data: list):
        """Fill the table with data"""

        table.blockSignals(True)
        table.clearContents()
        addrow = []
        if table.objectName() == 'meta':
            addrow = [[{'value':'', 'iseditable': True}, {'value':'', 'iseditable': True}]]
        table.setRowCount(len(data + addrow))

        for i, row in enumerate(data + addrow):
            key = row[0]['value']
            if table.objectName()=='bids' and key=='suffix' and self.target_datatype in self.bidscoindatatypes:
                table.setItem(i, 0, MyWidgetItem('suffix', iseditable=False))
                suffixes = self.allowed_suffixes.get(self.target_datatype, [''])
                suffix_dropdown = self.suffix_dropdown = QComboBox()
                suffix_dropdown.addItems(suffixes)
                suffix_dropdown.setCurrentIndex(suffix_dropdown.findText(self.target_run['bids'].get('suffix','')))
                suffix_dropdown.currentIndexChanged.connect(self.suffix_dropdown_change)
                suffix_dropdown.setToolTip('The suffix that sets the different run types apart. First make sure the "Data type" dropdown-menu is set correctly before chosing the right suffix here')
                for n, suffix in enumerate(suffixes):
                    suffix_dropdown.setItemData(n, bids.get_suffixhelp(suffix), QtCore.Qt.ToolTipRole)
                table.setCellWidget(i, 1, self.spacedwidget(suffix_dropdown))
                continue
            for j, item in enumerate(row):
                value = item.get('value')
                if table.objectName()=='bids' and isinstance(value, list):
                    value_dropdown = QComboBox()
                    value_dropdown.addItems(value[0:-1])
                    value_dropdown.setCurrentIndex(value[-1])
                    value_dropdown.currentIndexChanged.connect(partial(self.bidscell2run, i, j))
                    if j == 0:
                        value_dropdown.setToolTip(bids.get_entityhelp(key))
                    table.setCellWidget(i, j, self.spacedwidget(value_dropdown))
                else:
                    value_item = MyWidgetItem(value, iseditable=item['iseditable'])
                    if table.objectName() == 'properties':
                        if j == 1:
                            value_item.setToolTip('The (regexp) matching pattern that for this property')
                        if j == 2:
                            value_item.setToolTip(bids.get_propertieshelp(key))
                    elif table.objectName()=='attributes' and j==0:
                        value_item.setToolTip(bids.get_attributeshelp(key))
                    elif table.objectName()=='bids' and j==0:
                        value_item.setToolTip(bids.get_entityhelp(key))
                    elif table.objectName()=='meta' and j==0:
                        value_item.setToolTip(bids.get_metahelp(key))
                    table.setItem(i, j, value_item)

        table.blockSignals(False)

    def propertiescell2run(self, rowindex: int, colindex: int):
        """Source attribute value has been changed"""

        # Only if cell was actually clicked, update (i.e. not when BIDS datatype changes)
        if colindex == 1:
            key      = self.properties_table.item(rowindex, 0).text().strip()
            value    = self.properties_table.item(rowindex, 1).text().strip()
            oldvalue = self.target_run['properties'].get(key)
            if oldvalue is None:
                oldvalue = ''

            # Only if cell was changed, update
            if key and value != oldvalue:
                answer = QMessageBox.question(self, f"Edit {self.dataformat} attributes",
                                              f'It is discouraged to change {self.dataformat} attribute values unless you are an expert user. Do you really want to change "{oldvalue}" to "{value}"?',
                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer == QMessageBox.Yes:
                    LOGGER.warning(f"Expert usage: User has set {self.dataformat}['{key}'] from '{oldvalue}' to '{value}' for {self.target_run['provenance']}")
                    self.target_run['properties'][key] = value
                else:
                    self.properties_table.blockSignals(True)
                    self.properties_table.item(rowindex, 1).setText(oldvalue)
                    self.properties_table.blockSignals(False)

    def attributescell2run(self, rowindex: int, colindex: int):
        """Source attribute value has been changed"""

        # Only if cell was actually clicked, update (i.e. not when BIDS datatype changes)
        if colindex == 1:
            key      = self.attributes_table.item(rowindex, 0).text().strip()
            value    = self.attributes_table.item(rowindex, 1).text()
            oldvalue = self.target_run['attributes'].get(key)
            if oldvalue is None:
                oldvalue = ''

            # Only if cell was changed, update
            if key and value!=oldvalue:
                answer = QMessageBox.question(self, f"Edit {self.dataformat} attributes",
                                              f'It is discouraged to change {self.dataformat} attribute values unless you are an expert user. Do you really want to change "{oldvalue}" to "{value}"?',
                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer == QMessageBox.Yes:
                    LOGGER.warning(f"Expert usage: User has set {self.dataformat}['{key}'] from '{oldvalue}' to '{value}' for {self.target_run['provenance']}")
                    self.target_run['attributes'][key] = value
                else:
                    self.attributes_table.blockSignals(True)
                    self.attributes_table.item(rowindex, 1).setText(oldvalue)
                    self.attributes_table.blockSignals(False)

    def bidscell2run(self, rowindex: int, colindex: int):
        """BIDS attribute value has been changed"""

        # Only if cell was actually clicked, update (i.e. not when BIDS datatype changes) and store the data in the target_run
        if colindex == 1:
            key = self.bids_table.item(rowindex, 0).text()
            if hasattr(self.bids_table.cellWidget(rowindex, 1), 'spacedwidget'):
                dropdown = self.bids_table.cellWidget(rowindex, 1).spacedwidget
                value    = [dropdown.itemText(n) for n in range(len(dropdown))] + [dropdown.currentIndex()]
                oldvalue = self.target_run['bids'].get(key)
            else:
                value    = self.bids_table.item(rowindex, 1).text().strip()
                oldvalue = self.target_run['bids'].get(key)
            if oldvalue is None:
                oldvalue = ''

            # Only if cell was changed, update
            if key and value != oldvalue:
                # Validate user input against BIDS or replace the (dynamic) bids-value if it is a run attribute
                self.bids_table.blockSignals(True)
                if isinstance(value, str) and ('<<' not in value or '>>' not in value):
                    value = bids.cleanup_value(self.datasource.dynamicvalue(value))
                    self.bids_table.item(rowindex, 1).setText(value)
                if key == 'run' and '<<' in oldvalue and '>>' in oldvalue:
                    answer = QMessageBox.question(self, f"Edit bids entities",
                                                  f'It is highly discouraged to change the <<dynamic>> run-index unless you are an expert user. Do you really want to change "{oldvalue}" to "{value}"?',
                                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if answer==QMessageBox.Yes:
                        LOGGER.warning(f"Expert usage: User has set bids['{key}'] from '{oldvalue}' to '{value}' for {self.target_run['provenance']}")
                    else:
                        value = oldvalue
                        self.bids_table.item(rowindex, 1).setText(oldvalue)
                        LOGGER.info(f"User has set bids['{key}'] from '{oldvalue}' to '{value}' for {self.target_run['provenance']}")
                else:
                    LOGGER.info(f"User has set bids['{key}'] from '{oldvalue}' to '{value}' for {self.target_run['provenance']}")
                self.bids_table.blockSignals(False)
                self.target_run['bids'][key] = value
                self.refresh_bidsname()

    def metacell2run(self, rowindex: int, colindex: int):
        """Source meta value has been changed"""

        key      = self.meta_table.item(rowindex, 0).text().strip()
        value    = self.meta_table.item(rowindex, 1).text().strip()
        oldvalue = self.target_run['meta'].get(key)
        if oldvalue is None:
            oldvalue = ''
        if value != oldvalue:
            # Replace the (dynamic) value
            if '<<' not in value or '>>' not in value:
                value = self.datasource.dynamicvalue(value, cleanup=False)
                self.meta_table.blockSignals(True)
                self.meta_table.item(rowindex, 1).setText(value)
                self.meta_table.blockSignals(False)
            LOGGER.info(f"User has set meta['{key}'] from '{oldvalue}' to '{value}' for {self.target_run['provenance']}")

        # Read all the meta-data from the table and store it in the target_run
        self.target_run['meta'] = {}
        for n in range(self.meta_table.rowCount()):
            key_   = self.meta_table.item(n, 0).text().strip()
            value_ = self.meta_table.item(n, 1).text().strip()
            if key_:
                try: value_ = ast.literal_eval(value_)      # Converting string to list
                except (ValueError, SyntaxError): pass
                self.target_run['meta'][key_] = value_
            elif value_:
                QMessageBox.warning(self, 'Input error', f"Please enter a key-name (left cell) for the '{value_}' value in row {n+1}")

        # Refresh the table if needed, i.e. delete empty rows or add a new row if a key is defined on the last row
        if (not key and not value) or (key and rowindex + 1 == self.meta_table.rowCount()):
            _, _, _, data_meta = self.run2data()
            self.fill_table(self.meta_table, data_meta)

    def change_run(self, suffix_idx):
        """
        Resets the edit dialog window with a new target_run from the template bidsmap after a suffix- or datatype-change

        :param suffix_idx: The suffix or index number that will used to extract the run from the template bidsmap
        """

        # Add a check to see if we can still read the source data
        if not Path(self.target_run['provenance']).is_file():
            LOGGER.warning(f"Can no longer find the source file: {self.target_run['provenance']}")
            QMessageBox.warning(self, 'Edit BIDS mapping', f"Cannot reliably change the datatype and/or suffix because the source file '{self.target_run['provenance']}' can no longer be found.\n\nPlease restore the source data or use the `bidsmapper -s` option to solve this issue. Resetting the run-item now...")
            self.reset()
            return

        old_entities = self.target_run['bids']

        # Get the new target_run from the template
        self.target_run = bids.get_run(self.template_bidsmap, self.target_datatype, suffix_idx, self.datasource)

        # Transfer the old entity data to the new run-item if possible and if it's not there yet
        for key, val in old_entities.items():
            if val and key in self.target_run['bids'] and not self.target_run['bids'][key]:
                self.target_run['bids'][key] = val

        # Insert the new target_run in our target_bidsmap
        bids.update_bidsmap(self.target_bidsmap, self.current_datatype, self.target_run)

        # Now that we have updated the bidsmap, we can also update the current_datatype
        self.current_datatype = self.target_datatype

        # Reset the edit window with the new target_run
        self.reset(refresh=True)

    def datatype_dropdown_change(self):
        """Update the BIDS values and BIDS output name section when the dropdown selection has been taking place"""

        self.target_datatype = self.datatype_dropdown.currentText()

        LOGGER.info(f"User has changed the BIDS data type from '{self.current_datatype}' to '{self.target_datatype}' for {self.target_run['provenance']}")

        self.change_run(0)

    def suffix_dropdown_change(self):
        """Update the BIDS values and BIDS output name section when the dropdown selection has been taking place"""

        target_suffix = self.suffix_dropdown.currentText()

        LOGGER.info(f"User has changed the BIDS suffix from '{self.target_run['bids'].get('suffix')}' to '{target_suffix}' for {self.target_run['provenance']}")

        self.change_run(target_suffix)

    def refresh_bidsname(self):
        """Updates the bidsname with the current (edited) bids values"""

        bidsname = (Path(self.target_datatype)/bids.get_bidsname(self.subid, self.sesid, self.target_run)).with_suffix('.*')

        font = self.bidsname_textbox.font()
        if self.target_datatype in self.unknowndatatypes:
            self.bidsname_textbox.setToolTip(f"Red: This imaging data type is not part of BIDS but will be converted to a BIDS-like entry in the {self.unknowndatatypes} folder. Click 'OK' if you want your BIDS output data to look like this")
            self.bidsname_textbox.setTextColor(QtGui.QColor('red'))
            font.setStrikeOut(False)
        elif self.target_datatype in self.ignoredatatypes:
            self.bidsname_textbox.setToolTip("Gray / Strike-out: This imaging data type will be ignored and not converted BIDS. Click 'OK' if you want your BIDS output data to look like this")
            self.bidsname_textbox.setTextColor(QtGui.QColor('gray'))
            font.setStrikeOut(True)
        elif not bids.check_run(self.target_datatype, self.target_run):
            self.bidsname_textbox.setToolTip(f"Red: This name is not valid according to the BIDS standard -- see terminal output for more info")
            self.bidsname_textbox.setTextColor(QtGui.QColor('red'))
            font.setStrikeOut(False)
        else:
            self.bidsname_textbox.setToolTip(f"Green: This '{self.target_datatype}' imaging data type is part of BIDS. Click 'OK' if you want your BIDS output data to look like this")
            self.bidsname_textbox.setTextColor(QtGui.QColor('green'))
            font.setStrikeOut(False)
        self.bidsname_textbox.setFont(font)
        self.bidsname_textbox.clear()
        self.bidsname_textbox.textCursor().insertText(str(bidsname))

    def reset(self, refresh: bool=False):
        """Resets the edit with the target_run if refresh=True or otherwise with the original source_run (=default)"""

        # Reset the target_run to the source_run
        if not refresh:
            LOGGER.info('User resets the BIDS mapping')
            self.current_datatype = self.source_datatype
            self.target_datatype  = self.source_datatype
            self.target_run       = copy.deepcopy(self.source_run)
            self.target_bidsmap   = copy.deepcopy(self.source_bidsmap)

            # Reset the datatype dropdown menu
            self.datatype_dropdown.blockSignals(True)
            self.datatype_dropdown.setCurrentIndex(self.datatype_dropdown.findText(self.target_datatype))
            self.datatype_dropdown.blockSignals(False)

        # Refresh the source attributes and BIDS values with data from the target_run
        data_properties, data_attributes, data_bids, data_meta = self.run2data()

        # Refresh the existing tables
        self.fill_table(self.properties_table, data_properties)
        self.fill_table(self.attributes_table, data_attributes)
        self.fill_table(self.bids_table, data_bids)
        self.fill_table(self.meta_table, data_meta)

        # Refresh the BIDS output name
        self.refresh_bidsname()

    def accept_run(self):
        """Save the changes to the target_bidsmap and send it back to the main window: Finished!"""

        if not bids.check_run(self.target_datatype, self.target_run):
            answer = QMessageBox.question(self, 'Edit BIDS mapping', f'The "{self.target_datatype}/*_{self.target_run["bids"].get("suffix")}" run is not valid according to the BIDS standard. Do you want to go back and edit the run?',
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                return
            LOGGER.warning(f'The "{self.bidsname_textbox.toPlainText()}" run is not valid according to the BIDS standard")')

        if self.target_datatype=='fmap' and not (self.target_run['meta'].get('B0FieldSource') or self.target_run['meta'].get('B0FieldIdentifier') or self.target_run['meta'].get('IntendedFor')):
            answer = QMessageBox.question(self, 'Edit BIDS mapping', "The 'B0FieldIdentifier/IntendedFor' meta-data is left empty\n\nDo you want to go back and "
                                                                     "set this data (recommended)?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if answer in (QMessageBox.Cancel, QMessageBox.Yes):
                return
            LOGGER.warning(f"'B0FieldIdentifier/IntendedFor' fieldmap data was not set")

        LOGGER.info(f'User has approved the edit')
        if re.sub('<(?!.*<).*? object at .*?>','',str(self.target_run)) != re.sub('<(?!.*<).*? object at .*?>','',str(self.source_run)):    # Ignore the memory address of the datasource object
            bids.update_bidsmap(self.target_bidsmap, self.current_datatype, self.target_run)

            self.done_edit.emit(self.target_bidsmap)
            self.done(1)

        else:
            self.done(2)

    def export_run(self):
        """Export the editted run to a (e.g. template) bidsmap on disk"""

        yamlfile, _ = QFileDialog.getOpenFileName(self, 'Export run item to (template) bidsmap',
                                                  str(bidscoin.bidsmap_template), 'YAML Files (*.yaml *.yml);;All Files (*)')
        if yamlfile:
            LOGGER.info(f'Exporting run item: bidsmap[{self.dataformat}][{self.target_datatype}] -> {yamlfile}')
            yamlfile   = Path(yamlfile)
            bidsmap, _ = bids.load_bidsmap(yamlfile, Path(), report=False)
            bids.append_run(bidsmap, self.target_run)
            bids.save_bidsmap(yamlfile, bidsmap)
            QMessageBox.information(self, 'Edit BIDS mapping', f"Successfully exported:\n\nbidsmap[{self.dataformat}][{self.target_datatype}] -> {yamlfile}")

    def inspect_sourcefile(self, rowindex: int=None, colindex: int=None):
        """When double clicked, show popup window"""

        if colindex in (0,2):
            if rowindex == 0:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(self.target_run['provenance']).parent)))
            if rowindex == 1:
                self.popup = InspectWindow(Path(self.target_run['provenance']))
                self.popup.show()
                self.popup.scrollbar.setValue(0)  # This can only be done after self.popup.show()

    @staticmethod
    def spacedwidget(alignedwidget, align='left'):
        """Place the widget in a QHBoxLayout and add a stretcher next to it. Return the widget as widget.spacedwidget"""

        widget = QtWidgets.QWidget()
        layout = QHBoxLayout()
        if align != 'left':
            layout.addStretch()
            layout.addWidget(alignedwidget)
        else:
            layout.addWidget(alignedwidget)
            layout.addStretch()
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)
        widget.spacedwidget = alignedwidget
        return widget

    def get_help(self):
        """Open web page for help"""
        help_url = HELP_URLS.get(self.target_datatype, HELP_URL_DEFAULT)
        webbrowser.open(help_url)


class InspectWindow(QDialog):

    def __init__(self, filename: Path):
        super().__init__()

        if bids.is_dicomfile(filename):
            text = str(dcmread(filename, force=True))
        elif bids.is_parfile(filename) or filename.suffix.lower() in ('.spar', '.txt', '.text'):
            text = filename.read_text()
        elif filename.suffix == '.7':
            try:
                from spec2nii.GE.ge_read_pfile import Pfile
                text = ''
                hdr = Pfile(filename).hdr
                for field in hdr._fields_:
                    data = getattr(hdr, field[0])
                    if type(data) == bytes:
                        try:
                            data = data.decode('UTF-8')
                        except UnicodeDecodeError:
                            pass
                    text += f"{field[0]}:\t {data}\n"
            except ImportError as perror:
                text = f"Could not inspect: {filename}"
                LOGGER.info(f"Could not import spec2nii to read {filename}\n{perror}")
        else:
            text = f"Could not inspect: {filename}"
            LOGGER.info(text)

        self.setWindowIcon(QtGui.QIcon(str(BIDSCOIN_ICON)))
        self.setWindowTitle(str(filename))
        self.setWindowFlags(self.windowFlags() & QtCore.Qt.WindowContextHelpButtonHint & QtCore.Qt.WindowMinMaxButtonsHint & QtCore.Qt.WindowCloseButtonHint)

        layout = QVBoxLayout(self)

        textbrowser = QTextBrowser(self)
        textbrowser.setFont(QtGui.QFont("Courier New"))
        textbrowser.insertPlainText(text)
        textbrowser.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        textbrowser.setWhatsThis(f"This window displays all available source attributes")
        self.scrollbar = textbrowser.verticalScrollBar()        # For setting the slider to the top (can only be done after self.show()
        layout.addWidget(textbrowser)

        buttonbox = QDialogButtonBox(self)
        buttonbox.setStandardButtons(QDialogButtonBox.Ok)
        buttonbox.button(QDialogButtonBox.Ok).setToolTip('Close this window')
        buttonbox.accepted.connect(self.close)
        layout.addWidget(buttonbox)

        # Set the layout-width to the width of the text
        fontmetrics = QtGui.QFontMetrics(textbrowser.font())
        textwidth   = fontmetrics.size(0, text).width()
        self.resize(min(textwidth + 70, 1200), self.height())


class MyQTableWidget(QTableWidget):

    def __init__(self, minimum: bool=True):
        super().__init__()

        self.setAlternatingRowColors(False)
        self.setShowGrid(False)

        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setMinimumHeight(2 * (ROW_HEIGHT + 8))
        self.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)

        self.minimizeheight(minimum)

    def minimizeheight(self, minimum: bool=True):
        """Set the vertical QSizePolicy to Minimum"""

        self.minimum = minimum

        if minimum:
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        else:
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)


class MyWidgetItem(QTableWidgetItem):

    def __init__(self, value: Union[str,Path]='', iseditable: bool=True):
        """A QTableWidgetItem that is editable or not and that converts integer values to string"""

        super().__init__()
        self.setText(value)
        self.seteditable(iseditable)

    def setText(self, p_str):
        """Catch int and None"""

        if p_str is None:
            p_str = ''

        super(MyWidgetItem, self).setText(str(p_str))

    def seteditable(self, iseditable: bool=True):
        """Make the WidgetItem editable"""

        self.iseditable = iseditable

        if iseditable:
            self.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEditable)
            self.setForeground(QtGui.QColor('black'))
        else:
            self.setFlags(QtCore.Qt.ItemIsEnabled)
            self.setForeground(QtGui.QColor('gray'))


def bidseditor(bidsfolder: str, bidsmapfile: str='', templatefile: str='') -> None:
    """
    Collects input and launches the bidseditor GUI

    :param bidsfolder:      The name of the BIDS root folder
    :param bidsmapfile:     The name of the bidsmap YAML-file
    :param templatefile:    The name of the bidsmap template YAML-file
    """

    bidsfolder   = Path(bidsfolder).resolve()
    bidsmapfile  = Path(bidsmapfile)
    templatefile = Path(templatefile)

    # Start logging
    bidscoin.setup_logging(bidsfolder/'code'/'bidscoin'/'bidseditor.log')
    LOGGER.info('')
    LOGGER.info('-------------- START BIDSeditor ------------')
    LOGGER.info(f">>> bidseditor bidsfolder={bidsfolder} bidsmap={bidsmapfile} template={templatefile}")

    # Obtain the initial bidsmap info
    template_bidsmap, templatefile = bids.load_bidsmap(templatefile, bidsfolder/'code'/'bidscoin')
    input_bidsmap, bidsmapfile     = bids.load_bidsmap(bidsmapfile,  bidsfolder/'code'/'bidscoin')
    if input_bidsmap.get('Options'):
        template_bidsmap['Options'] = input_bidsmap['Options']      # Always use the options of the input bidsmap

    # Start the Qt-application
    app = QApplication(sys.argv)
    app.setApplicationName(f"{bidsmapfile} - BIDS editor {bidscoin.version()}")
    mainwin = MainWindow(bidsfolder, input_bidsmap, template_bidsmap, datasaved=True)
    mainwin.show()
    app.exec()

    LOGGER.info('-------------- FINISHED! -------------------')
    LOGGER.info('')

    bidscoin.reporterrors()


def main():
    """Console script usage"""

    # Parse the input arguments and run bidseditor
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description=textwrap.dedent(__doc__),
                                     epilog=textwrap.dedent("""
                                         examples:
                                           bidseditor /project/foo/bids
                                           bidseditor /project/foo/bids -t bidsmap_dccn.yaml
                                           bidseditor /project/foo/bids -b my/custom/bidsmap.yaml"""))

    parser.add_argument('bidsfolder',           help='The destination folder with the (future) bids data')
    parser.add_argument('-b','--bidsmap',       help='The study bidsmap file with the mapping heuristics. If the bidsmap filename is relative (i.e. no "/" in the name) then it is assumed to be located in bidsfolder/code/bidscoin. Default: bidsmap.yaml', default='bidsmap.yaml')
    parser.add_argument('-t','--template',      help='The template bidsmap file with the default heuristics (this could be provided by your institute). If the bidsmap filename is relative (i.e. no "/" in the name) then it is assumed to be located in bidsfolder/code/bidscoin. Default: bidsmap_dccn.yaml', default=bidscoin.bidsmap_template)
    args = parser.parse_args()

    bidseditor(bidsfolder   = args.bidsfolder,
               bidsmapfile  = args.bidsmap,
               templatefile = args.template)


if __name__ == '__main__':
    LOGGER = logging.getLogger(f"bidscoin.{Path(__file__).stem}")
    main()

else:
    LOGGER = logging.getLogger(__name__)
