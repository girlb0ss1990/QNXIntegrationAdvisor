cmake_minimum_required(VERSION 3.16)
project(motor_pid_controller C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_COMPILER gcc)
add_compile_options(-O2 -Wall -march=native)

add_executable(motor_pid src/main.c src/pid.c src/motor_io.c src/config_watch.c)
target_link_libraries(motor_pid pthread rt m)

install(TARGETS motor_pid DESTINATION bin)
install(FILES motor-pid.service DESTINATION lib/systemd/system)
