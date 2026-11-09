cmake_minimum_required(VERSION 3.16)
project(vitals_monitor C)

set(CMAKE_C_STANDARD 11)
add_compile_options(-O2 -Wall -march=native)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "vitals-monitor only supports Linux")
endif()

find_package(Threads REQUIRED)
add_executable(vitals_monitor src/vitals.c)
target_link_libraries(vitals_monitor Threads::Threads rt)
