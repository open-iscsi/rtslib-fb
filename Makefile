# This file is part of RTSLib.
# Copyright (c) 2011-2013 by Datera, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#     WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#     License for the specific language governing permissions and limitations
#     under the License.
#

PKGNAME = rtslib-fb
NAME = rtslib
GIT_BRANCH = $$(git branch | grep \* | tr -d \*)
VERSION = $$(basename $$(git describe --tags | tr - . | grep -o '[0-9].*$$'))

all:
	@echo "Usage:"
	@echo
	@echo "  make deb         - Builds debian packages."
	@echo "  make rpm         - Builds rpm packages."
	@echo "  make release     - Generates the release tarball."
	@echo
	@echo "  make clean       - Cleanup the local repository build files."
	@echo "  make cleanall    - Also remove dist/*"

clean:
	@rm -fv ${NAME}/*.pyc ${NAME}/*.html
	@rm -frv ${NAME}.egg-info MANIFEST build
	@rm -frv debian/tmp
	@rm -fv build-stamp
	@rm -fv dpkg-buildpackage.log dpkg-buildpackage.version
	@rm -frv *.rpm
	@rm -fv debian/files debian/*.log debian/*.substvars
	@rm -frv debian/${PKGNAME}-doc/ debian/python2.5-${PKGNAME}/
	@rm -frv debian/python2.6-${PKGNAME}/ debian/python-${PKGNAME}/
	@rm -frv results
	@rm -fv example/rpm/*.spec *.spec example/rpm/sed* sed*
	@rm -frv ${PKGNAME}-*
	@echo "Finished cleanup."

cleanall: clean
	@rm -frv dist

release: build/release-stamp
build/release-stamp:
	@mkdir -p build
	@echo "Exporting the repository files..."
	@git archive ${GIT_BRANCH} --prefix ${PKGNAME}-${VERSION}/ \
		| (cd build; tar xfp -)
	@echo "Cleaning up the target tree..."
	@rm -f build/${PKGNAME}-${VERSION}/Makefile
	@rm -f build/${PKGNAME}-${VERSION}/.gitignore
	@echo "Fixing version string..."
	@sed -i "s/__version__ = .*/__version__ = '${VERSION}'/g" \
		build/${PKGNAME}-${VERSION}/${NAME}/__init__.py
	@echo "Generating rpm specfile from template..."
	@cd build/${PKGNAME}-${VERSION}; \
		for spectmpl in example/rpm/*.spec.tmpl; do \
			sed -i "s/Version:\( *\).*/Version:\1${VERSION}/g" $${spectmpl}; \
			mv $${spectmpl} $$(basename $${spectmpl} .tmpl); \
		done; \
		rm -r example/rpm
	@echo "Generating rpm changelog..."
	@( \
		version=$$(basename $$(git describe HEAD --tags | tr - .)); \
		author=$$(git show HEAD --format="format:%an <%ae>" -s); \
		date=$$(git show HEAD --format="format:%ad" -s \
			| awk '{print $$1,$$2,$$3,$$5}'); \
		hash=$$(git show HEAD --format="format:%H" -s); \
	   	echo '* '"$${date} $${author} $${version}-1"; \
		echo "  - Generated from git commit $${hash}."; \
	) >> $$(ls build/${PKGNAME}-${VERSION}/*.spec)
	@echo "Generating debian changelog..."
	@( \
		version=$$(basename $$(git describe HEAD --tags | tr - . | grep -o '[0-9].*$$')); \
		author=$$(git show HEAD --format="format:%an <%ae>" -s); \
		date=$$(git show HEAD --format="format:%aD" -s); \
		day=$$(git show HEAD --format='format:%ai' -s \
			| awk '{print $$1}' \
			| awk -F '-' '{print $$3}' | sed 's/^0/ /g'); \
		date=$$(echo $${date} \
			| awk '{print $$1, "'"$${day}"'", $$3, $$4, $$5, $$6}'); \
		hash=$$(git show HEAD --format="format:%H" -s); \
		echo "${PKGNAME} ($${version}) unstable; urgency=low"; \
		echo; \
		echo "  * Generated from git commit $${hash}."; \
		echo; \
		echo " -- $${author}  $${date}"; \
		echo; \
	) > build/${PKGNAME}-${VERSION}/example/debian/changelog
	@find build/${PKGNAME}-${VERSION}/ -exec \
		touch -t $$(date -d @$$(git show -s --format="format:%at") \
			+"%Y%m%d%H%M.%S") {} \;
	@mkdir -p dist
	@cd build; tar -c --owner=0 --group=0 --numeric-owner \
		--format=gnu -b20 --quoting-style=escape \
		-f ../dist/${PKGNAME}-${VERSION}.tar \
		$$(find ${PKGNAME}-${VERSION} -type f | sort)
	@gzip -6 -n dist/${PKGNAME}-${VERSION}.tar
	@echo "Generated release tarball:"
	@echo "    $$(ls dist/${PKGNAME}-${VERSION}.tar.gz)"
	@touch build/release-stamp

deb: release build/deb-stamp
build/deb-stamp:
	@echo "Building debian packages..."
	@cd build/${PKGNAME}-${VERSION}; \
		dpkg-buildpackage -rfakeroot -us -uc
	@mv build/*_${VERSION}_*.deb dist/
	@echo "Generated debian packages:"
	@for pkg in $$(ls dist/*_${VERSION}_*.deb); do echo "  $${pkg}"; done
	@touch build/deb-stamp

rpm: release build/rpm-stamp
build/rpm-stamp:
	@echo "Building rpm packages..."
	@mkdir -p build/rpm
	@build=$$(pwd)/build/rpm; dist=$$(pwd)/dist/; rpmbuild \
		--define "_topdir $${build}" --define "_sourcedir $${dist}" \
		--define "_rpmdir $${build}" --define "_buildir $${build}" \
		--define "_srcrpmdir $${build}" -ba build/${PKGNAME}-${VERSION}/*.spec
	@mv build/rpm/*-${VERSION}*.src.rpm dist/
	@mv build/rpm/*/*-${VERSION}*.rpm dist/
	@echo "Generated rpm packages:"
	@for pkg in $$(ls dist/*-${VERSION}*.rpm); do echo "  $${pkg}"; done
	@touch build/rpm-stamp
