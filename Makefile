# This file is part of RTSLib Community Edition.
# Copyright (c) 2011 by RisingTide Systems LLC
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 (AGPLv3).
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

NAME = rtslib
LIB = /usr/share
DOC = ${LIB}/doc/
SETUP = ./setup.py
CLEAN = ./bin/clean
GENDOC = ./bin/gendoc

all: usage
usage:
	@echo "Usage:"
	@echo "  make install - Install rtslib"
	@echo "  make installdocs - Install the documentation"
	@echo "Developer targets:"
	@echo "  make packages - Generate the Debian and RPM packages"
	@echo "  make doc      - Generate the documentation"
	@echo "  make clean    - Cleanup the local repository"
	@echo "  make sdist    - Build the source tarball"
	@echo "  make bdist    - Build the installable tarball"

install:
	${SETUP} install

doc:
	./bin/gen_changelog
	${GENDOC}

installdocs: doc
	@test -e ${DOC} || \
	    echo "Could not find ${DOC}; check the makefile variables."
	@test -e ${DOC}
	cp -r doc/* ${DOC}/${NAME}/

clean:
	${CLEAN}
	./bin/gen_changelog_cleanup

packages: clean doc
	dpkg-buildpackage -rfakeroot | tee dpkg-buildpackage.log
	./bin/gen_changelog_cleanup
	grep "source version" dpkg-buildpackage.log | awk '{print $$4}' > dpkg-buildpackage.version
	@test -e dist || mkdir dist
	mv ../${NAME}_$$(cat dpkg-buildpackage.version).dsc dist
	mv ../${NAME}_$$(cat dpkg-buildpackage.version)_*.changes dist
	mv ../${NAME}_$$(cat dpkg-buildpackage.version).tar.gz dist
	mv ../*${NAME}*$$(cat dpkg-buildpackage.version)*.deb dist
	@test -e build || mkdir build
	cd build; alien --scripts -k -g -r ../dist/rtslib-doc_$$(cat ../dpkg-buildpackage.version)_all.deb
	cd build/rtslib-doc-*; mkdir usr/share/doc/packages
	cd build/rtslib-doc-*; mv usr/share/doc/rtslib-doc usr/share/doc/packages/
	cd build/rtslib-doc-*; perl -pi -e "s,/usr/share/doc/rtslib-doc,/usr/share/doc/packages/rtslib-doc,g" *.spec
	cd build/rtslib-doc-*; perl -pi -e "s,%%{ARCH},noarch,g" *.spec
	cd build/rtslib-doc-*; perl -pi -e "s,%post,%posttrans,g" *.spec
	cd build/rtslib-doc-*; rpmbuild --buildroot $$PWD -bb *.spec
	cd build; alien --scripts -k -g -r ../dist/python-rtslib_$$(cat ../dpkg-buildpackage.version)_all.deb; cd ..
	cd build/python-rtslib-*; mkdir usr/share/doc/packages
	cd build/python-rtslib-*; mv usr/share/doc/python-rtslib usr/share/doc/packages/
	cd build/python-rtslib-*; perl -pi -e "s,/usr/share/doc/python-rtslib,/usr/share/doc/packages/python-rtslib,g" *.spec
	cd build/python-rtslib-*; perl -pi -e 's/Group:/Requires: python >= 2.5\nGroup:/g' *.spec
	cd build/python-rtslib-*; perl -pi -e "s,%%{ARCH},noarch,g" *.spec
	cd build/python-rtslib-*; perl -pi -e "s,%post,%posttrans,g" *.spec
	cd build/python-rtslib-*; rpmbuild --buildroot $$PWD -bb *.spec
	mv build/*.rpm dist
	rm dpkg-buildpackage.log dpkg-buildpackage.version

sdist: clean doc
	${SETUP} sdist

bdist: clean doc
	${SETUP} bdist

