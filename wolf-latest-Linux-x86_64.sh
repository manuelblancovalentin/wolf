#!/bin/sh
#
# NAME:  Wolf
# VER:   1.0.0
# PLAT:  linux-64
# MD5:   d41d8cd98f00b204e9800998ecf8427e

########################################################
# [@manuelbv]: First lines were shamelessly copied from
#       miniconda3 installation script header
########################################################
export OLD_LD_LIBRARY_PATH=$LD_LIBRARY_PATH
unset LD_LIBRARY_PATH
if ! echo "$0" | grep '\.sh$' > /dev/null; then
    printf 'Please run using "bash" or "sh", but not "." or "source"\\n' >&2
    return 1
fi

# Determine RUNNING_SHELL; if SHELL is non-zero use that.
if [ -n "$SHELL" ]; then
    RUNNING_SHELL="$SHELL"
else
    if [ "$(uname)" = "Darwin" ]; then
        RUNNING_SHELL=/bin/bash
    else
        if [ -d /proc ] && [ -r /proc ] && [ -d /proc/$$ ] && [ -r /proc/$$ ] && [ -L /proc/$$/exe ] && [ -r /proc/$$/exe ]; then
            RUNNING_SHELL=$(readlink /proc/$$/exe)
        fi
        if [ -z "$RUNNING_SHELL" ] || [ ! -f "$RUNNING_SHELL" ]; then
            RUNNING_SHELL=$(ps -p $$ -o args= | sed 's|^-||')
            case "$RUNNING_SHELL" in
                */*)
                    ;;
                default)
                    RUNNING_SHELL=$(which "$RUNNING_SHELL")
                    ;;
            esac
        fi
    fi
fi

# Some final fallback locations
if [ -z "$RUNNING_SHELL" ] || [ ! -f "$RUNNING_SHELL" ]; then
    if [ -f /bin/bash ]; then
        RUNNING_SHELL=/bin/bash
    else
        if [ -f /bin/sh ]; then
            RUNNING_SHELL=/bin/sh
        fi
    fi
fi

if [ -z "$RUNNING_SHELL" ] || [ ! -f "$RUNNING_SHELL" ]; then
    printf 'Unable to determine your shell. Please set the SHELL env. var and re-run\\n' >&2
    exit 1
fi

THIS_DIR=$(DIRNAME=$(dirname "$0"); cd "$DIRNAME"; pwd)
THIS_FILE=$(basename "$0")
THIS_PATH="$THIS_DIR/$THIS_FILE"
PREFIX=$HOME/wolf
BATCH=0
FORCE=0
SKIP_SCRIPTS=0
TEST=0
REINSTALL=0
USAGE="
usage: $0 [options]

Installs WOLF 1.0.0

-b           run install in batch mode (without manual intervention),
             it is expected the license terms are agreed upon
-f           no error if install prefix already exists
-h           print this help message and exit
-p PREFIX    install prefix, defaults to $PREFIX, must not contain spaces.
-s           skip running pre/post-link/install scripts
-u           update an existing installation
"

if which getopt > /dev/null 2>&1; then
    OPTS=$(getopt bfhp:sut "$*" 2>/dev/null)
    if [ ! $? ]; then
        printf "%s\\n" "$USAGE"
        exit 2
    fi

    eval set -- "$OPTS"

    while true; do
        case "$1" in
            -h)
                printf "%s\\n" "$USAGE"
                exit 2
                ;;
            -b)
                BATCH=1
                shift
                ;;
            -f)
                FORCE=1
                shift
                ;;
            -p)
                PREFIX="$2"
                shift
                shift
                ;;
            -s)
                SKIP_SCRIPTS=1
                shift
                ;;
            -u)
                FORCE=1
                shift
                ;;
            --)
                shift
                break
                ;;
            *)
                printf "ERROR: did not recognize option '%s', please try -h\\n" "$1"
                exit 1
                ;;
        esac
    done
else
    while getopts "bfhp:sut" x; do
        case "$x" in
            h)
                printf "%s\\n" "$USAGE"
                exit 2
            ;;
            b)
                BATCH=1
                ;;
            f)
                FORCE=1
                ;;
            p)
                PREFIX="$OPTARG"
                ;;
            s)
                SKIP_SCRIPTS=1
                ;;
            u)
                FORCE=1
                ;;
            ?)
                printf "ERROR: did not recognize option '%s', please try -h\\n" "$x"
                exit 1
                ;;
        esac
    done
fi

if [ "$BATCH" = "0" ] # interactive mode
then
    if [ "$(uname)" != "Linux" ]; then
        printf "WARNING:\\n"
        printf "    Your operating system does not appear to be Linux, \\n"
        printf "    but you are trying to install a Linux version of Wolf.\\n"
        printf "    Are sure you want to continue the installation? [yes|no]\\n"
        printf "[no] >>> "
        read -r ans
        if [ "$ans" != "yes" ] && [ "$ans" != "Yes" ] && [ "$ans" != "YES" ] && \
           [ "$ans" != "y" ]   && [ "$ans" != "Y" ]
        then
            printf "Aborting installation\\n"
            exit 2
        fi
    fi
    printf "\\n"
    printf "Welcome to Wolf 1.0.0\\n"
    printf "\\n"
    printf "In order to continue the installation process, please review the license\\n"
    printf "agreement.\\n"
    printf "Please, press ENTER to continue\\n"
    printf ">>> "
    read -r dummy
    pager="cat"
    if command -v "more" > /dev/null 2>&1; then
      pager="more"
    fi
    "$pager" <<EOF
===================================
End User License Agreement - Wolf
===================================

Copyright 2015-2021, Northwestern University & Fermilab.

All rights reserved under the 3-clause BSD License:

This End User License Agreement (the "Agreement") is a legal agreement between you and  Northwestern University, Inc. (" Northwestern University") and governs your use of Wolf.

Subject to the terms of this Agreement, Northwestern University hereby grants you a non-exclusive, non-transferable license to:

  * Install and use the Wolf.
  * Modify and create derivative works of sample source code delivered in Wolf subject to the Terms of Service for the Repository (as defined hereinafter) available at https://github.com/manuelblancovalentin/wolf/terms-of-service, and

  * Redistribute code files in source (if provided to you by Northwestern University as source) and binary forms, with or without modification subject to the requirements set forth below.

Northwestern University may, at its option, make available patches, workarounds or other updates to Wolf. Unless the updates are provided with their separate governing terms, they are deemed part of Wolf licensed to you as provided in this Agreement. This Agreement does not entitle you to any support for Wolf.

Northwestern University reserves all rights not expressly granted to you in this Agreement.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

  * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
  * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
  * Neither the name of Anaconda nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

You acknowledge that, as between you and Northwestern University, Northwestern University owns all right, title, and interest, including all intellectual property rights, in and to Wolf and, with respect to third-party products distributed with or through Wolf, the applicable third-party licensors own all right, title and interest, including all intellectual property rights, in and to such products. If you send or transmit any communications or materials to Wolf suggesting or recommending changes to the software or documentation, including without limitation, new features or functionality relating thereto, or any comments, questions, suggestions or the like ("Feedback"), Anaconda is free to use such Feedback. You hereby assign to Northwestern University all right, title, and interest in, and Northwestern University is free to use, without any attribution or compensation to any party, any ideas, know-how, concepts, techniques or other intellectual property rights contained in the Feedback, for any purpose whatsoever, although Northwestern University is not required to use any Feedback.

DISCLAIMER
==========

THIS SOFTWARE IS PROVIDED BY NORTHWESTERN UNIVERSITY AND ITS CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL NORTHWESTERN UNIVERSITY BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

TO THE MAXIMUM EXTENT PERMITTED BY LAW, NORTHWESTERN UNIVERSITY AND ITS AFFILIATES SHALL NOT BE LIABLE FOR ANY SPECIAL, INCIDENTAL, PUNITIVE OR CONSEQUENTIAL DAMAGES, OR ANY LOST PROFITS, LOSS OF USE, LOSS OF DATA OR LOSS OF GOODWILL, OR THE COSTS OF PROCURING SUBSTITUTE PRODUCTS, ARISING OUT OF OR IN CONNECTION WITH THIS AGREEMENT OR THE USE OR PERFORMANCE OF NORTHWESTERN UNIVERSITY INDIVIDUAL EDITION, WHETHER SUCH LIABILITY ARISES FROM ANY CLAIM BASED UPON BREACH OF CONTRACT, BREACH OF WARRANTY, TORT (INCLUDING NEGLIGENCE), PRODUCT LIABILITY OR ANY OTHER CAUSE OF ACTION OR THEORY OF LIABILITY. IN NO EVENT WILL THE TOTAL CUMULATIVE LIABILITY OF ANACONDA AND ITS AFFILIATES UNDER OR ARISING OUT OF THIS AGREEMENT EXCEED US$10.00.

Miscellaneous
=============

If you want to terminate this Agreement, you may do so by discontinuing use of Wolf. Northwestern University may, at any time, terminate this Agreement and the license granted hereunder if you fail to comply with any term of this Agreement. Upon any termination of this Agreement, you agree to promptly discontinue use of the Miniconda and destroy all copies in your possession or control. Upon any termination of this Agreement all provisions survive except for the licenses granted to you.

This Agreement is governed by and construed in accordance with the internal laws of the State of Illinois without giving effect to any choice or conflict of law provision or rule that would require or permit the application of the laws of any jurisdiction other than those of the State of Illinois. Any legal suit, action, or proceeding arising out of or related to this Agreement or the licenses granted hereunder by you must be instituted exclusively in the federal courts of the United States or the courts of the State of Illinois in each case located in Cook County, Illinois, and you irrevocably submit to the jurisdiction of such courts in any such suit, action, or proceeding.

Notice of Third Party Software Licenses
=======================================

Wolf provides access to a repository (the "Repository") which contains software packages or tools licensed on an open source basis from third parties and binary packages of these third party tools. These third party software packages or tools are provided on an "as is" basis and are subject to their respective license agreements as well as this Agreement and the Terms of Service for the Repository located at https://github.com/manuelblancovalentin/wolf/terms-of-service; provided, however, no restriction contained in the Terms of Service shall be construed so as to limit Your ability to download the packages contained in Miniconda provided you comply with the license for each such package. These licenses may be accessed from within the Wolf software[1]. 

Export; Cryptography Notice
===========================

You must comply with all domestic and international export laws and regulations that apply to the software, which include restrictions on destinations, end users, and end use. Wolf includes cryptographic software. The country in which you currently reside may have restrictions on the import, possession, use, and/or re-export to another country, of encryption software. BEFORE using any encryption software, please check your country's laws, regulations and policies concerning the import, possession, or use, and re-export of encryption software, to see if this is permitted. See the Wassenaar Arrangement http://www.wassenaar.org/ for more information.

Northwestern University has self-classified this software as Export Commodity Control Number (ECCN) EAR99, which includes mass market information security software using or performing cryptographic functions with asymmetric algorithms. No license is required for export of this software to non-embargoed countries.

Last updated January 25, 2022

EOF
    printf "\\n"
    printf "Do you accept the license terms? [yes|no]\\n"
    printf "[no] >>> "
    read -r ans
    while [ "$ans" != "yes" ] && [ "$ans" != "Yes" ] && [ "$ans" != "YES" ] && \
          [ "$ans" != "no" ]  && [ "$ans" != "No" ]  && [ "$ans" != "NO" ]
    do
        printf "Please answer 'yes' or 'no':'\\n"
        printf ">>> "
        read -r ans
    done
    if [ "$ans" != "yes" ] && [ "$ans" != "Yes" ] && [ "$ans" != "YES" ]
    then
        printf "The license agreement wasn't approved, aborting installation.\\n"
        exit 2
    fi
    printf "\\n"
    printf "Wolf will now be installed into this location:\\n"
    printf "%s\\n" "$PREFIX"
    printf "\\n"
    printf "  - Press ENTER to confirm the location\\n"
    printf "  - Press CTRL-C to abort the installation\\n"
    printf "  - Or specify a different location below\\n"
    printf "\\n"
    printf "[%s] >>> " "$PREFIX"
    read -r user_prefix
    if [ "$user_prefix" != "" ]; then
        case "$user_prefix" in
            *\ * )
                printf "ERROR: Cannot install into directories with spaces\\n" >&2
                exit 1
                ;;
            *)
                eval PREFIX="$user_prefix"
                ;;
        esac
    fi
fi # !BATCH

case "$PREFIX" in
    *\ * )
        printf "ERROR: Cannot install into directories with spaces\\n" >&2
        exit 1
        ;;
esac

if [ "$FORCE" = "0" ] && [ -e "$PREFIX" ]; then
    printf "ERROR: File or directory already exists: '%s'\\n" "$PREFIX" >&2
    printf "If you want to update an existing installation, use the -u option.\\n" >&2
    exit 1
elif [ "$FORCE" = "1" ] && [ -e "$PREFIX" ]; then
    REINSTALL=1
fi


if ! mkdir -p "$PREFIX"; then
    printf "ERROR: Could not create directory: '%s'\\n" "$PREFIX" >&2
    exit 1
fi

PREFIX=$(cd "$PREFIX"; pwd)
export PREFIX

printf "PREFIX=%s\\n" "$PREFIX"

# verify the MD5 sum of the tarball appended to this header
MD5=$(tail -n +556 "$THIS_PATH" | md5sum -)
if ! echo "$MD5" | grep d41d8cd98f00b204e9800998ecf8427e >/dev/null; then
    printf "WARNING: md5sum mismatch of tar archive\\n" >&2
    printf "expected: d41d8cd98f00b204e9800998ecf8427e\\n" >&2
    printf "     got: %s\\n" "$MD5" >&2
fi

# extract the tarball appended to this header, this creates the *.tar.bz2 files
# for all the packages which get installed below
cd "$PREFIX"

# Clone github


chmod +x "$CONDA_EXEC"

export TMP_BACKUP="$TMP"
export TMP=$PREFIX/install_tmp

printf "Unpacking payload ...\n"
{
    dd if="$THIS_PATH" bs=1 skip=15240903               count=12601                     2>/dev/null
    dd if="$THIS_PATH" bs=16384        skip=931                    count=3140                  2>/dev/null
    dd if="$THIS_PATH" bs=1 skip=66699264                   count=10490                   2>/dev/null
} | "$CONDA_EXEC" constructor --extract-tar --prefix "$PREFIX"

"$CONDA_EXEC" constructor --prefix "$PREFIX" --extract-conda-pkgs || exit 1

PRECONDA="$PREFIX/preconda.tar.bz2"
"$CONDA_EXEC" constructor --prefix "$PREFIX" --extract-tarball < "$PRECONDA" || exit 1
rm -f "$PRECONDA"

PYTHON="$PREFIX/bin/python"
MSGS="$PREFIX/.messages.txt"
touch "$MSGS"
export FORCE

# original issue report:
# https://github.com/ContinuumIO/anaconda-issues/issues/11148
# First try to fix it (this apparently didn't work; QA reported the issue again)
# https://github.com/conda/conda/pull/9073
mkdir -p ~/.conda > /dev/null 2>&1

CONDA_SAFETY_CHECKS=disabled \
CONDA_EXTRA_SAFETY_CHECKS=no \
CONDA_ROLLBACK_ENABLED=no \
CONDA_CHANNELS=https://repo.anaconda.com/pkgs/main,https://repo.anaconda.com/pkgs/main,https://repo.anaconda.com/pkgs/r,https://repo.anaconda.com/pkgs/pro \
CONDA_PKGS_DIRS="$PREFIX/pkgs" \
"$CONDA_EXEC" install --offline --file "$PREFIX/pkgs/env.txt" -yp "$PREFIX" || exit 1



POSTCONDA="$PREFIX/postconda.tar.bz2"
"$CONDA_EXEC" constructor --prefix "$PREFIX" --extract-tarball < "$POSTCONDA" || exit 1
rm -f "$POSTCONDA"

rm -f $PREFIX/conda.exe
rm -f $PREFIX/pkgs/env.txt

rm -rf $PREFIX/install_tmp
export TMP="$TMP_BACKUP"

mkdir -p $PREFIX/envs

if [ -f "$MSGS" ]; then
  cat "$MSGS"
fi
rm -f "$MSGS"
# handle .aic files
$PREFIX/bin/python -E -s "$PREFIX/pkgs/.cio-config.py" "$THIS_PATH" || exit 1
printf "installation finished.\\n"

if [ "$BATCH" = "0" ]; then
    # Interactive mode.
    BASH_RC="$HOME"/.bashrc
    DEFAULT=no
    printf "Do you wish the installer to initialize Miniconda3\\n"
    printf "by running conda init? [yes|no]\\n"
    printf "[%s] >>> " "$DEFAULT"
    read -r ans
    if [ "$ans" = "" ]; then
        ans=$DEFAULT
    fi
    if [ "$ans" != "yes" ] && [ "$ans" != "Yes" ] && [ "$ans" != "YES" ] && \
       [ "$ans" != "y" ]   && [ "$ans" != "Y" ]
    then
        printf "\\n"
        printf "You have chosen to not have conda modify your shell scripts at all.\\n"
        printf "To activate conda's base environment in your current shell session:\\n"
        printf "\\n"
        printf "eval \"\$($PREFIX/bin/conda shell.YOUR_SHELL_NAME hook)\" \\n"
        printf "\\n"
        printf "To install conda's shell functions for easier access, first activate, then:\\n"
        printf "\\n"
        printf "conda init\\n"
        printf "\\n"
    else
        if [[ $SHELL = *zsh ]]
        then
            $PREFIX/bin/conda init zsh
        else
            $PREFIX/bin/conda init
        fi
    fi
    printf "If you'd prefer that conda's base environment not be activated on startup, \\n"
    printf "   set the auto_activate_base parameter to false: \\n"
    printf "\\n"
    printf "conda config --set auto_activate_base false\\n"
    printf "\\n"

    printf "Thank you for installing Miniconda3!\\n"
fi # !BATCH


exit 0