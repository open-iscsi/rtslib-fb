rtslib-fb
=========

A Python object API for managing the Linux LIO kernel target
------------------------------------------------------------
rtslib-fb is an object-based Python library for configuring the LIO
generic SCSI target, present in Linux kernel.


rtslib-fb development
---------------------
rtslib-fb is licensed under the Apache 2.0 license. Contributions are welcome.

Since rtslib-fb is used most often with targetcli-fb, the targetcli-fb
mailing should be used for rtslib-fb discussion.

 * Mailing list: [targetcli-fb-devel](https://lists.fedorahosted.org/mailman/listinfo/targetcli-fb-devel)
 * Source repo: [GitHub](https://github.com/open-iscsi/rtslib-fb)
 * Bugs: [GitHub](https://github.com/open-iscsi/rtslib-fb/issues) or [Trac](https://fedorahosted.org/targetcli-fb/)
 * Tarballs: [fedorahosted](https://fedorahosted.org/releases/t/a/targetcli-fb/)

Packages
--------
rtslib-fb is packaged for a number of Linux distributions including
RHEL,
[Fedora](https://apps.fedoraproject.org/packages/python-rtslib),
openSUSE, Arch Linux,
[Gentoo](https://packages.gentoo.org/packages/dev-python/rtslib-fb), and
[Debian](https://tracker.debian.org/pkg/python-rtslib-fb).

Contribute
----------
rtslib complies with PEP 621 and as such can be built and installed with tools like `build` and `pip`.

For development, consider using [Hatch](https://hatch.pypa.io):  
`hatch shell` to create and enter a Python virtualenv with the project installed in editable mode  
`pre-commit install` to enable pre-commit hooks  
`hatch build` to create tarball and wheel  

"fb" -- "free branch"
---------------------
rtslib-fb is a fork of the "rtslib" code written by RisingTide Systems.
