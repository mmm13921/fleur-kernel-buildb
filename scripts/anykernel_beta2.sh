#!/sbin/sh
# AnyKernel3 installer for Fleux Beta 2 / MT6781 fleur.

properties() { '
kernel.string=Fleux Beta 2 - 2.2GHz for fleur
do.devicecheck=1
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=fleur
'; }

BLOCK=auto;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

. tools/ak3-core.sh;

ui_print " ";
ui_print "Fleux Beta 2";
ui_print "MT6781 / fleur - big cluster target: 2.2 GHz";
ui_print "Top VPROC OPP: 1.15625 V";
ui_print "Thermal and watchdog protections unchanged";
ui_print " ";

dump_boot;
write_boot;
