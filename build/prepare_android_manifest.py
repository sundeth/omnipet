"""Build a manifest-only Android library for Gradle's standard manifest merger.

p4a's extra_manifest_application_arguments inserts XML *attributes*, not child
elements. A tiny AAR registers receivers without patching its bootstrap template.
Run before Buildozer; also used by build_android.ps1 in the WSL staging tree.
"""
import io
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(directory):
    directory = Path(directory)
    receivers = (directory / 'receivers.xml').read_text(encoding='utf-8')
    # An omitted targetSdkVersion defaults to 1; the manifest merger then adds
    # legacy compatibility permissions such as READ_PHONE_STATE to the app.
    manifest = ('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                'package="org.omnipet.offline">'
                '<uses-sdk android:minSdkVersion="21" android:targetSdkVersion="33" />'
                '<application>' + receivers +
                '</application></manifest>')
    jar = io.BytesIO()
    with ZipFile(jar, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
    path = directory / 'pet-notifications.aar'
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('AndroidManifest.xml', manifest)
        archive.writestr('classes.jar', jar.getvalue())
    return path


if __name__ == '__main__':
    print(build(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'android_src'))
