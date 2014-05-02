# RTSLib

RTSlib is a Python library that provides the API to the Linux Kernel SCSI
Target subsystem (LIO), its backend storage objects subsystem (TCM) as well
as third-party Target Fabric Modules.

RTSLib allows direct manipulation of all SCSI Target objects like storage
objects, SCSI targets, TPGs, LUNs and ACLs. It is part of the Linux Kernel's
SCSI Target's userspace management tools.

## Usage scenarios

RTSLib is used as the foundation for targetcli, the Linux Kernel's SCSI Target
configuration CLI and shell, in embedded storage systems and appliances, 
commercial NAS and SAN systems as well as a tool for sysadmins writing their
own scripts to configure the SCSI Target subsystem.

## Installation

RTSLib is currently part of several Linux distributions, either under the
rtslib name or python-rtslib. In most cases, simply installing the version
packaged by your favorite Linux distribution is the best way to get it running.


## Building from source

The packages are very easy to build and install from source as long as
you're familiar with your Linux Distribution's package manager:

1.  Clone the github repository for rtslib using `git clone
    https://github.com/Datera/rtslib.git`.

2.  Make sure build dependencies are installed. To build rtslib, you will need:

	* GNU Make.
	* python 2.6 or 2.7
	* A few python libraries: ipaddr, netifaces, configobj, python-epydoc
	* A working LaTeX installation and ghostscript for building the
	  documentation, for example texlive-latex.
	* Your favorite distribution's package developement tools, like rpm for
	  Redhat-based systems or dpkg-dev and debhelper for Debian systems.

3.  From the cloned git repository, run `make deb` to generate a Debian
    package, or `make rpm` for a Redhat package.

4.  The newly built packages will be generated in the dist/ directory.

5.  To cleanup the repository, use `make clean` or `make cleanall` which also
    removes dist/* files.

## Documentation

The RTSLib packages do ship with a full API documentation in both HTML and PDF
formats, typically in /usr/share/doc/python-rtslib/doc/.

Depending on your Linux distribution, the documentation might be shipped in a
separate package.

An other good source of information is the http://linux-iscsi.org wiki,
offering many resources such as (not necessarily up-to-date) copies of the
RTSlib API Reference Guide (HTML at http://linux-iscsi.org/Doc/rtslib/html or
PDF at http://linux-iscsi.org/Doc/rtslib/rtslib-API-reference.pdf), and the
Targetcli User's Guide at http://linux-iscsi.org/wiki/targetcli.

## Mailing-list

All contributions, suggestions and bugfixes are welcome!

To report a bug, submit a patch or simply stay up-to-date on the Linux SCSI
Target developments, you can subscribe to the Linux Kernel SCSI Target
development mailing-list by sending an email message containing only
`subscribe target-devel` to <mailto:majordomo@vger.kernel.org>

The archives of this mailing-list can be found online at
http://dir.gmane.org/gmane.linux.scsi.target.devel

## Author

RTSlib was developed by Datera, Inc.
http://www.datera.io

The original author and current maintainer is
Jerome Martin, at <mailto:jxm@netiant.com>
