Summary: Modular Assembler
Name: yasm
Version: 1.2.0
Release: 1%{?dist}
# See COPYING for the detail, there is quite a lot!
License: BSD and (GPLv2+ or Artistic or LGPLv2+) and LGPLv2
Group: Development/Languages
URL: http://yasm.tortall.net/
Source: http://www.tortall.net/projects/yasm/releases/yasm-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root
BuildRequires: bison, byacc, xmlto, gettext-devel

%description
Yasm is a complete rewrite of the NASM assembler under the "new" BSD License
(some portions are under other licenses, see COPYING for details). It is
designed from the ground up to allow for multiple assembler syntaxes to be
supported (eg, NASM, TASM, GAS, etc.) in addition to multiple output object
formats and even multiple instruction sets. Another primary module of the
overall design is an optimizer module.


%package devel
Summary: Header files and static libraries for the yasm Modular Assembler
Group: Development/Libraries
Requires: %{name} = %{version}-%{release}
Provides: %{name}-static = %{version}-%{release}

%description devel
Yasm is a complete rewrite of the NASM assembler under the "new" BSD License
(some portions are under other licenses, see COPYING for details). It is
designed from the ground up to allow for multiple assembler syntaxes to be
supported (eg, NASM, TASM, GAS, etc.) in addition to multiple output object
formats and even multiple instruction sets. Another primary module of the
overall design is an optimizer module.
Install this package if you need to rebuild applications that use yasm.


%prep
%setup -q


%build
%configure
make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}


%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc Artistic.txt AUTHORS BSD.txt COPYING GNU*
%{_bindir}/vsyasm
%{_bindir}/yasm
%{_bindir}/ytasm
%{_mandir}/man1/yasm.1*

%files devel
%defattr(-,root,root,-)
%{_includedir}/libyasm/
%{_includedir}/libyasm-stdint.h
%{_includedir}/libyasm.h
%{_libdir}/libyasm.a
%{_mandir}/man7/yasm_*.7*


%changelog
* Thu Mar 15 2012 Matthias Saou <matthias@saou.eu> 1.2.0-1
- Update to 1.2.0 (#750234).
- Minor spec file cleanups (keep EPEL compatibility, #802162).

* Sat Jan 14 2012 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_17_Mass_Rebuild

* Tue Feb 08 2011 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_15_Mass_Rebuild

* Sun Aug 15 2010 Matthias Saou <http://freshrpms.net/> 1.1.0-1
- Update to 1.1.0 (#622240).

* Thu Jul 29 2010 Matthias Saou <http://freshrpms.net/> 1.0.1-2
- Provide static sub-package from devel (#609626).

* Sun May 23 2010 Matthias Saou <http://freshrpms.net/> 1.0.1-1
- Update to 1.0.1 (#593250).

* Wed Apr 28 2010 Matthias Saou <http://freshrpms.net/> 1.0.0-1
- Update to 1.0.0 (#580872).
- Include new vsyasm binary.

* Mon Dec  7 2009 Matthias Saou <http://freshrpms.net/> 0.8.0-1
- Update to 0.8.0 (#523729).
- Include new ytasm binary.

* Mon Jul 27 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.7.2-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_12_Mass_Rebuild

* Wed Feb 25 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.7.2-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_11_Mass_Rebuild

* Wed Dec 24 2008 Matthias Saou <http://freshrpms.net/> 0.7.2-1
- Update to 0.7.2.
- Remove useless /sbin/ldconfig calls, as we don't ship any shared library.
- Update summary.

* Sat Sep  6 2008 Tom "spot" Callaway <tcallawa@redhat.com> 0.7.1-2
- fix license tag so that it doesn't trigger a false positive on the check
  script.

* Tue May 20 2008 Matthias Saou <http://freshrpms.net/> 0.7.1-1
- Update to 0.7.1.

* Tue May 13 2008 Matthias Saou <http://freshrpms.net/> 0.7.0-1
- Update to 0.7.0.

* Tue Feb 19 2008 Fedora Release Engineering <rel-eng@fedoraproject.org>
- Autorebuild for GCC 4.3

* Mon Sep 24 2007 Matthias Saou <http://freshrpms.net/> 0.6.2-1
- Update to 0.6.2.

* Thu Aug 23 2007 Matthias Saou <http://freshrpms.net/> 0.6.1-3
- Rebuild for new BuildID feature.

* Fri Aug  3 2007 Matthias Saou <http://freshrpms.net/> 0.6.1-2
- Update License field, it wasn't simply "BSD"...

* Tue Jun 19 2007 Matthias Saou <http://freshrpms.net/> 0.6.1-1
- Update to 0.6.1.

* Sun Feb 25 2007 Matthias Saou <http://freshrpms.net/> 0.6.0-1
- Update to 0.6.0.

* Mon Aug 28 2006 Matthias Saou <http://freshrpms.net/> 0.5.0-2
- FC6 rebuild.
- Require the same release in the devel sub-package.

* Fri Jul 14 2006 Matthias Saou <http://freshrpms.net/> 0.5.0-1
- Update to 0.5.0.
- Remove empty files from %%doc.
- There are no more shared libraries, only a static one, so update %%files.

* Mon Mar  6 2006 Matthias Saou <http://freshrpms.net/> 0.4.0-6
- FC5 rebuild.

* Thu Feb  9 2006 Matthias Saou <http://freshrpms.net/> 0.4.0-5
- Rebuild for new gcc/glibc.

* Sun May 22 2005 Jeremy Katz <katzj@redhat.com> - 0.4.0-4
- rebuild on all arches

* Fri Apr  7 2005 Michael Schwendt <mschwendt[AT]users.sf.net>
- rebuilt

* Mon Feb 14 2005 David Woodhouse <dwmw2@infradead.org> 0.4.0-2
- Fix corruption in genmacro

* Fri Jan 28 2005 Matthias Saou <http://freshrpms.net/> 0.4.0-1
- Initial RPM release.

