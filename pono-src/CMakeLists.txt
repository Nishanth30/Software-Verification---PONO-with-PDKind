cmake_minimum_required(VERSION 3.18...4.0)

project(pono)

set(PONO_MAJOR 0) # Major component of Pono version
set(PONO_MINOR 1) # Minor component of Pono version
set(PONO_RELEASE 1) # Release component of Pono version

# Generate compilation database compile_commands.json
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Retrieve the current version via Git
execute_process(
  COMMAND git describe --always --dirty
  WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
  RESULT_VARIABLE GIT_DESCRIBE_STATUS
  OUTPUT_VARIABLE PONO_VERSION
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(GIT_DESCRIBE_STATUS AND NOT GIT_DESCRIBE_STATUS EQUAL 0)
  set(PONO_VERSION "v${PONO_MAJOR}.${PONO_MINOR}.${PONO_RELEASE}")
endif()

# handle different versions of CMake
if(NOT CMAKE_CXX_COMPILER_VERSION VERSION_LESS 8.0 AND NOT APPLE)
  set(CMAKE_CXX17_STANDARD_COMPILE_OPTION "-std=c++17")
  set(CMAKE_CXX17_EXTENSION_COMPILE_OPTION "-std=gnu++17")
elseif(NOT CMAKE_CXX_COMPILER_VERSION VERSION_LESS 5.1 OR APPLE)
  set(CMAKE_CXX17_STANDARD_COMPILE_OPTION "-std=c++1z")
  set(CMAKE_CXX17_EXTENSION_COMPILE_OPTION "-std=gnu++1z")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_definitions(-DPONO_SRC_DIR=${PROJECT_SOURCE_DIR})

if(APPLE)
  set(SHARED_LIB_EXT "dylib")
  # Add Homebrew paths for macOS
  list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew")
  include_directories("/opt/homebrew/include")
  link_directories("/opt/homebrew/lib")
else()
  set(SHARED_LIB_EXT "so")
endif()

if(WITH_BOOLECTOR)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DWITH_BOOLECTOR")
endif()

if(WITH_MSAT)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DWITH_MSAT")
endif()

if(WITH_YICES2)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DWITH_YICES2")
endif()

if(WITH_Z3)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DWITH_Z3")
endif()

if(WITH_PROFILING)
  find_library(GOOGLE_PERF profiler REQUIRED)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DWITH_PROFILING")
endif()

if(APPLE)
  list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew/opt/bison")
  list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew/opt/flex")
endif()

find_package(BISON 3.4.2 REQUIRED)
if(BISON_FOUND)
  get_filename_component(BISON_PARENT_DIR "${BISON_EXECUTABLE}" DIRECTORY)
  message("-- Adding bison lib: ${BISON_PARENT_DIR}/../lib")
  link_directories("${BISON_PARENT_DIR}/../lib/")
endif()

find_package(FLEX 2.6.4 REQUIRED)
if(NOT FLEX_INCLUDE_DIRS)
  set(FLEX_INCLUDE_DIRS /opt/homebrew/opt/flex/include)
endif()
message(STATUS "FLEX_INCLUDE_DIRS: ${FLEX_INCLUDE_DIRS}")

if(NOT DEFINED SMT_SWITCH_DIR)
  set(SMT_SWITCH_DIR "${PROJECT_SOURCE_DIR}/deps/smt-switch")
endif()

find_package(PkgConfig REQUIRED)

# Check that dependencies are there
list(APPEND CMAKE_PREFIX_PATH "${SMT_SWITCH_DIR}/deps/install")

pkg_check_modules(GMPXX REQUIRED gmpxx)
pkg_check_modules(BITWUZLA REQUIRED bitwuzla)

# --- OVERRIDE SMT-SWITCH CHECK ---
# Manually setting paths because automated find_path fails on some macOS setups
set(smt-switch_INCLUDE_DIR "${SMT_SWITCH_DIR}/local/include" CACHE PATH "Path to smt-switch headers" FORCE)
set(smt-switch_LIB_DIR "${SMT_SWITCH_DIR}/build" CACHE PATH "Path to smt-switch libs" FORCE)

message(STATUS "Manual override: smt-switch_INCLUDE_DIR=${smt-switch_INCLUDE_DIR}")

# Check for required library files manually
if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch.a")
  message(FATAL_ERROR "Missing smt-switch library at ${smt-switch_LIB_DIR}/libsmt-switch.a")
endif()

if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch-bitwuzla.a")
  message(FATAL_ERROR "Missing smt-switch Bitwuzla library")
endif()

if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch-cvc5.a")
  message(FATAL_ERROR "Missing smt-switch cvc5 library")
endif()
# --- END OVERRIDE ---

if(WITH_BOOLECTOR)
  if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch-btor.a")
    message(FATAL_ERROR "Missing smt-switch Boolector library")
  endif()
endif()

if(WITH_MSAT)
  if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch-msat.a")
    message(FATAL_ERROR "Missing smt-switch mathsat library")
  endif()
endif()

if(WITH_YICES2)
  if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch-yices2.a")
    message(FATAL_ERROR "Missing smt-switch Yices2 library")
  endif()
endif()

if(WITH_Z3)
  find_package(Z3 REQUIRED)
  if(NOT EXISTS "${smt-switch_LIB_DIR}/libsmt-switch-z3.a")
    message(FATAL_ERROR "Missing smt-switch Z3 library")
  endif()
endif()

if(WITH_MSAT_IC3IA)
  if(NOT EXISTS "${PROJECT_SOURCE_DIR}/deps/ic3ia/build/libic3ia.a")
    message(FATAL_ERROR "Missing ic3ia library")
  endif()
endif()

if(WITH_COREIR)
  if(NOT EXISTS "${PROJECT_SOURCE_DIR}/deps/coreir/local/lib/libcoreir.${SHARED_LIB_EXT}")
    message(FATAL_ERROR "Missing coreir library.")
  endif()
endif()

list(APPEND CMAKE_PREFIX_PATH "${PROJECT_SOURCE_DIR}/deps/install")

# Check for Btor2Tools
find_path(Btor2Tools_INCLUDE_DIRS NAMES btor2parser.h)
if(NOT Btor2Tools_INCLUDE_DIRS)
  set(Btor2Tools_INCLUDE_DIRS "${PROJECT_SOURCE_DIR}/deps/install/include")
endif()

find_library(Btor2Tools_LIBRARIES NAMES btor2parser)
if(NOT Btor2Tools_LIBRARIES)
  set(Btor2Tools_LIBRARIES "${PROJECT_SOURCE_DIR}/deps/install/lib/libbtor2parser.a")
endif()

set(
  INCLUDE_DIRS
  "${PROJECT_SOURCE_DIR}"
  "${PROJECT_SOURCE_DIR}/contrib/"
  "${PROJECT_SOURCE_DIR}/contrib/optionparser-1.7/src"
  ${Btor2Tools_INCLUDE_DIRS}
  "${smt-switch_INCLUDE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}"
  ${GMPXX_INCLUDE_DIRS}
  ${FLEX_INCLUDE_DIRS}
)

set(
  SOURCES
  "${PROJECT_SOURCE_DIR}/core/ts.cpp"
  "${PROJECT_SOURCE_DIR}/core/rts.cpp"
  "${PROJECT_SOURCE_DIR}/core/fts.cpp"
  "${PROJECT_SOURCE_DIR}/core/unroller.cpp"
  "${PROJECT_SOURCE_DIR}/core/functional_unroller.cpp"
  "${PROJECT_SOURCE_DIR}/core/prop.cpp"
  "${PROJECT_SOURCE_DIR}/core/proverresult.cpp"
  "${PROJECT_SOURCE_DIR}/engines/prover.cpp"
  "${PROJECT_SOURCE_DIR}/engines/bmc.cpp"
  "${PROJECT_SOURCE_DIR}/engines/bmc_simplepath.cpp"
  "${PROJECT_SOURCE_DIR}/engines/cegar_ops_uf.cpp"
  "${PROJECT_SOURCE_DIR}/engines/cegar_values.cpp"
  "${PROJECT_SOURCE_DIR}/engines/ceg_prophecy_arrays.cpp"
  "${PROJECT_SOURCE_DIR}/engines/dual_approx_reach.cpp"
  "${PROJECT_SOURCE_DIR}/engines/ic3.cpp"
  "${PROJECT_SOURCE_DIR}/engines/ic3base.cpp"
  "${PROJECT_SOURCE_DIR}/engines/ic3bits.cpp"
  "${PROJECT_SOURCE_DIR}/engines/ic3ia.cpp"
  "${PROJECT_SOURCE_DIR}/engines/ic3sa.cpp"
  "${PROJECT_SOURCE_DIR}/engines/interpolantmc.cpp"
  "${PROJECT_SOURCE_DIR}/engines/interp_seq_mc.cpp"
  "${PROJECT_SOURCE_DIR}/engines/kinduction.cpp"
  "${PROJECT_SOURCE_DIR}/engines/kliveness.cpp"
  "${PROJECT_SOURCE_DIR}/engines/pdk_ind.cpp"
  "${PROJECT_SOURCE_DIR}/engines/mbic3.cpp"
  "${PROJECT_SOURCE_DIR}/engines/syguspdr.cpp"
  "${PROJECT_SOURCE_DIR}/frontends/btor2_encoder.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/array_abstractor.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/control_signals.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/implicit_predicate_abstractor.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/liveness_to_safety_translator.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/history_modifier.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/mod_ts_prop.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/ops_abstractor.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/prop_monitor.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/prophecy_modifier.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/static_coi.cpp"
  "${PROJECT_SOURCE_DIR}/modifiers/op_abstractor.cpp"
  "${PROJECT_SOURCE_DIR}/printers/btor2_witness_printer.cpp"
  "${PROJECT_SOURCE_DIR}/printers/vcd_witness_printer.cpp"
  "${PROJECT_SOURCE_DIR}/refiners/array_axiom_enumerator.cpp"
  "${PROJECT_SOURCE_DIR}/smt/available_solvers.cpp"
  "${PROJECT_SOURCE_DIR}/utils/fcoi.cpp"
  "${PROJECT_SOURCE_DIR}/utils/logger.cpp"
  "${PROJECT_SOURCE_DIR}/utils/make_provers.cpp"
  "${PROJECT_SOURCE_DIR}/utils/term_analysis.cpp"
  "${PROJECT_SOURCE_DIR}/utils/term_walkers.cpp"
  "${PROJECT_SOURCE_DIR}/utils/ts_analysis.cpp"
  "${PROJECT_SOURCE_DIR}/utils/ts_manipulation.cpp"
  "${PROJECT_SOURCE_DIR}/utils/sygus_ic3formula_helper.cpp"
  "${PROJECT_SOURCE_DIR}/utils/sygus_predicate_constructor.cpp"
  "${PROJECT_SOURCE_DIR}/utils/str_util.cpp"
  "${PROJECT_SOURCE_DIR}/utils/partial_model.cpp"
  "${PROJECT_SOURCE_DIR}/utils/syntax_analysis_common.cpp"
  "${PROJECT_SOURCE_DIR}/utils/syntax_analysis_walker.cpp"
  "${PROJECT_SOURCE_DIR}/utils/syntax_analysis.cpp"
  "${PROJECT_SOURCE_DIR}/options/options.cpp"
)

add_library(pono-lib "${PONO_LIB_TYPE}" ${SOURCES})
set_target_properties(pono-lib PROPERTIES OUTPUT_NAME pono)
target_compile_definitions(pono-lib PRIVATE "-DPONO_VERSION=\"${PONO_VERSION}\"")

target_include_directories(pono-lib PUBLIC ${INCLUDE_DIRS})

option(BUILD_PYTHON_BINDINGS "Build Python bindings")
if(BUILD_PYTHON_BINDINGS)
  add_subdirectory(python)
endif()

# Link against the libraries in the build folder
target_link_libraries(pono-lib PUBLIC "${smt-switch_LIB_DIR}/libsmt-switch-bitwuzla.a")
target_link_libraries(pono-lib PUBLIC "${smt-switch_LIB_DIR}/libsmt-switch-cvc5.a")
target_link_libraries(pono-lib PUBLIC "${smt-switch_LIB_DIR}/libsmt-switch.a")

if(WITH_BOOLECTOR)
  target_link_libraries(pono-lib PUBLIC "${smt-switch_LIB_DIR}/libsmt-switch-btor.a")
endif()

target_link_libraries(pono-lib PUBLIC ${Btor2Tools_LIBRARIES})
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libbitwuzla.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libbitwuzlals.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libbitwuzlabv.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libbitwuzlabb.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libcadical.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libcvc5.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libcvc5parser.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libpicpoly.a")
target_link_libraries(pono-lib PUBLIC "${PROJECT_SOURCE_DIR}/deps/smt-switch/deps/install/lib/libpicpolyxx.a")
target_link_libraries(pono-lib PUBLIC mpfr)
target_link_libraries(pono-lib PUBLIC ${GMPXX_LIBRARIES})
target_link_libraries(pono-lib PUBLIC pthread)

enable_testing()
add_subdirectory(tests EXCLUDE_FROM_ALL)

add_executable(pono-bin "${PROJECT_SOURCE_DIR}/pono.cpp")
set_target_properties(pono-bin PROPERTIES OUTPUT_NAME pono)

target_include_directories(
  pono-bin
  PUBLIC
    "${PROJECT_SOURCE_DIR}/utils"
    "${PROJECT_SOURCE_DIR}/core"
    "${PROJECT_SOURCE_DIR}/contrib/"
    "${PROJECT_SOURCE_DIR}/contrib/optionparser-1.7/src"
    "${smt-switch_INCLUDE_DIR}"
)

target_link_libraries(pono-bin PUBLIC pono-lib)

# install
install(TARGETS pono-lib DESTINATION lib)
install(TARGETS pono-bin DESTINATION bin)
