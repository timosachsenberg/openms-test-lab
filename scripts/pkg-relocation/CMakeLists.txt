cmake_minimum_required(VERSION 3.24)
project(OpenMSRelocationProbe C)

## Packages three stand-in app bundles the way the OpenMS macOS pkg does, with the packaging
## files of an OpenMS checkout (OPENMS_SOURCE_DIR): cmake/package_mac_productbuild.cmake, which
## writes the component plist, and cmake/package_components.cmake, which hands it to CPack.
## The bundles, the other components and the variables that the top-level CMakeLists.txt and
## cmake/package_general.cmake set are stand-ins; the bundles land where the real ones do,
## <prefix>/<name>.app in the Applications component. probe.py builds and checks the packages.

set(OPENMS_SOURCE_DIR "" CACHE PATH "OpenMS checkout whose packaging files build the probe")
set(PROBE_VERSION "3.7.0" CACHE STRING "Numeric version of the bundles and the package")
set(PROBE_SUFFIX "probe" CACHE STRING "Appended to the version in the name of the install folder")
option(PROBE_WITHOUT_PLIST "Leave out the component plist, as the packages before the fix did" OFF)

if(NOT EXISTS "${OPENMS_SOURCE_DIR}/cmake/package_mac_productbuild.cmake")
  message(FATAL_ERROR "OPENMS_SOURCE_DIR (${OPENMS_SOURCE_DIR}) is not an OpenMS checkout")
endif()

## Stand-ins for the top-level CMakeLists.txt and cmake/package_general.cmake
set(WITH_GUI ON)
set(PACKAGE_TYPE pkg)
set(OPENMS_GUI_APPLICATIONS_COMPONENT Applications)
set(OPENMS_PACKAGE_VERSION "${PROBE_VERSION}")
set(OPENMS_PACKAGE_VERSION_FULLSTRING "${PROBE_VERSION}-${PROBE_SUFFIX}")
set(OPENMS_HOST_DIRECTORY "${OPENMS_SOURCE_DIR}")
set(OPENMS_HOST_BINARY_DIRECTORY "${CMAKE_BINARY_DIR}")
set(INSTALL_BIN_DIR bin)
set(INSTALL_LIB_DIR lib)
set(INSTALL_PLUGIN_DIR lib/OpenMS/plugins)
set(INSTALL_SHARE_DIR share/OpenMS)
set(CPACK_BUNDLE_APPLE_CERT_APP "-")
set(CPACK_PACKAGE_NAME "OpenMS")
set(CPACK_PACKAGE_VENDOR "OpenMS.de")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "OpenMS relocation probe")
set(CPACK_PACKAGE_VERSION "${OPENMS_PACKAGE_VERSION}")
set(CPACK_RESOURCE_FILE_LICENSE "${OPENMS_SOURCE_DIR}/License.txt")
set(CPACK_RESOURCE_FILE_WELCOME "${OPENMS_SOURCE_DIR}/cmake/OpenMSPackageResourceWelcomeFile.txt")
set(CPACK_RESOURCE_FILE_README "${OPENMS_SOURCE_DIR}/cmake/OpenMSPackageResourceReadme.txt")
set(OPENMS_LOGO_NAME openms_logo_large_transparent.png)
set(OPENMS_LOGOSMALL_NAME openms_logo_corner_small.png)
list(APPEND CMAKE_MODULE_PATH "${OPENMS_SOURCE_DIR}/cmake/Modules")

## The app bundles, installed like add_mac_app_bundle() in src/openms_gui/add_mac_bundle.cmake
foreach(_app IN ITEMS INIFileEditor TOPPAS TOPPView)
  add_executable(${_app} MACOSX_BUNDLE probe.c)
  set_target_properties(${_app} PROPERTIES
    MACOSX_BUNDLE_GUI_IDENTIFIER "de.openms.${_app}"
    MACOSX_BUNDLE_BUNDLE_NAME ${_app}
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${OPENMS_PACKAGE_VERSION}"
    MACOSX_BUNDLE_BUNDLE_VERSION "${OPENMS_PACKAGE_VERSION}")
  install(TARGETS ${_app} BUNDLE DESTINATION . COMPONENT ${OPENMS_GUI_APPLICATIONS_COMPONENT})
  set_property(GLOBAL APPEND PROPERTY OPENMS_APP_BUNDLES ${_app})
endforeach()
## A TOPP tool and the other components of the real package
add_executable(FileInfo probe.c)
install(TARGETS FileInfo RUNTIME DESTINATION ${INSTALL_BIN_DIR} COMPONENT Applications)
foreach(_component IN ITEMS library library_cli library_gui Dependencies share)
  install(FILES probe.c DESTINATION ${INSTALL_SHARE_DIR}/probe RENAME ${_component}.txt COMPONENT ${_component})
endforeach()

## The OpenMS packaging files, in the order of the top-level CMakeLists.txt
set(PROJECT_SOURCE_DIR "${OPENMS_SOURCE_DIR}")
include(${OPENMS_SOURCE_DIR}/cmake/package_mac_productbuild.cmake)
if(PROBE_WITHOUT_PLIST)
  unset(APPLICATIONS_COMPONENT_PLIST)
endif()
include(CPack)
include(${OPENMS_SOURCE_DIR}/cmake/package_components.cmake)
