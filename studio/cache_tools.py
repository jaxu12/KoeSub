"""Only regenerable audio/peak caches are eligible; models and pipeline checkpoints never are."""
import re
from pathlib import Path


def candidates(root):
    root=Path(root).resolve();result=[]
    if not root.is_dir(): return result
    locations=[root]
    peaks=root/'waveforms'
    if peaks.is_dir() and not peaks.is_symlink() and not peaks.is_junction(): locations.append(peaks)
    for folder in locations:
        for path in folder.iterdir():
            if len(result)>=10000: return result
            if path.is_symlink() or path.is_junction() or not path.is_file(): continue
            pattern=r'audio-[0-9a-f]{24}(?:\.partial)?\.wav' if folder==root else r'[0-9a-f]{64}\.json'
            if re.fullmatch(pattern,path.name): result.append(path)
    return result


def delete_cache(root,selected):
    root=Path(root).resolve()
    allowed={p.resolve() for p in candidates(root)}
    selected=[Path(p) for p in selected]
    for path in selected:
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root) or path.resolve() not in allowed:
            raise ValueError('Wybrany plik nie jest rozpoznanym cache audio / waveformu. Nic nie usunięto.')
    freed=0;errors=[]
    for path in selected:
        try:
            size=path.stat().st_size;path.unlink();freed+=size
        except OSError as exc: errors.append(f'{path.name}: {exc}')
    return freed,errors


def show_cache_dialog(owner):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog,QLabel,QVBoxLayout,QTableWidget,QTableWidgetItem,QPushButton
    if owner.busy: return
    root=Path(owner.settings.cache_dir)
    files=candidates(root)
    dialog=QDialog(owner);dialog.setWindowTitle('Odbudowywalny cache • modele i checkpointy pozostają');dialog.resize(900,520)
    layout=QVBoxLayout(dialog)
    note=QLabel('Wybierz pliki do usunięcia. Audio i waveform można odbudować z filmu. '
                'Modele, logi, projekty oraz wyniki pipeline nie są na tej liście. Wykaz obejmuje do 10 000 plików.')
    note.setWordWrap(True);layout.addWidget(note)
    table=QTableWidget(len(files),3);table.setHorizontalHeaderLabels(['Usuń','Plik','Rozmiar'])
    table.setColumnWidth(0,60);table.setColumnWidth(1,620);table.horizontalHeader().setStretchLastSection(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for i,path in enumerate(files):
        item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsUserCheckable|Qt.ItemFlag.ItemIsEnabled);item.setCheckState(Qt.CheckState.Unchecked)
        table.setItem(i,0,item);table.setItem(i,1,QTableWidgetItem(str(path.relative_to(root))))
        table.setItem(i,2,QTableWidgetItem(f'{path.stat().st_size/1024**2:.2f} MiB'))
    layout.addWidget(table)
    summary=QLabel(f'Rozpoznany cache: {sum(p.stat().st_size for p in files)/1024**2:.1f} MiB');layout.addWidget(summary)
    remove=QPushButton('Usuń zaznaczone pliki cache')
    def apply():
        selected=[p for i,p in enumerate(files) if table.item(i,0).checkState()==Qt.CheckState.Checked]
        if not selected: return
        owner.editor_tools.wave.stop()
        freed,errors=delete_cache(root,selected)
        summary.setText(f'Zwolniono {freed/1024**2:.1f} MiB. '+('Błędy: '+'; '.join(errors) if errors else ''))
        remove.setEnabled(False)
    remove.clicked.connect(lambda:owner.guarded(apply));layout.addWidget(remove);dialog.exec()
