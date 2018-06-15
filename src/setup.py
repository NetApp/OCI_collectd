#!/usr/bin/python

import os
import argparse
import glob
import shlex
import shutil
import subprocess
import zipfile
from distutils.dir_util import copy_tree

ROOT_UID = 0
TEMP_DIRECTORY = '/tmp/collectd-oci-plugin'
COLLECTD_OCI_PLUGIN_DIRECTORY = '/usr/share/collectd/collectd-oci-plugin'
APT_INSTALL_COMMAND = 'apt-get install -y '
YUM_INSTALL_COMMAND = 'yum install -y '
ZYPPER_INSTALL_COMMAND = 'zypper --non-interactive install '
PYTHON_PACKAGES = ['requests']
COLLECTD_OCI_PLUGIN_URL = 'https://github.com/NetApp/OCI_collectd/archive/master.zip'
DOWNLOADED_PLUGIN_ZIP_FILE = TEMP_DIRECTORY + '/collectd-oci-master.zip'
PLUGIN_UNZIPPED_DIRECTORY = TEMP_DIRECTORY + '/OCI_collectd-master'
DOWNLOAD_COLLECTD_OCI_PLUGIN_COMMAND = 'curl --silent --location  --output ' \
                                       + DOWNLOADED_PLUGIN_ZIP_FILE + ' ' + COLLECTD_OCI_PLUGIN_URL
EPEL_RELEASE_7_RPM = 'http://dl.fedoraproject.org/pub/epel/7/x86_64/Packages/e/epel-release-7-11.noarch.rpm'
DOWNLOADED_EPEL_RELEASE_7_RPM = TEMP_DIRECTORY + '/epel-release-7-10.noarch.rpm'
DOWNLOAD_EPEL_RELEASE_7_RPM_COMMAND = 'curl --silent --location  --output ' \
                                      + DOWNLOADED_EPEL_RELEASE_7_RPM + ' ' + EPEL_RELEASE_7_RPM
LINUX_DISTRIBUTION = ''
LINUX_VERSION_ID = ''
OCI_HOST_NAME = ''
OCI_INTEGRATION_TOKEN = ''
REPORT_INTERVAL_SECONDS = 60
FAILED_REPORT_QUEUE_SIZE = 0
AGGREGATION_TYPE = 'average'
PLUGINS = 'cpu,memory'
LOGGING_LEVEL = 'info'


LINUX_DISTRIBUTION_TO_INSTALLER = {
    'Ubuntu': APT_INSTALL_COMMAND,
    'Debian GNU/Linux': APT_INSTALL_COMMAND,
    'Red Hat Enterprise Linux Server': YUM_INSTALL_COMMAND,
    'Amazon Linux AMI': YUM_INSTALL_COMMAND,
    'CentOS Linux': YUM_INSTALL_COMMAND,
    'SLES': ZYPPER_INSTALL_COMMAND,
}


LINUX_DISTRIBUTION_TO_DEPENDENT_PACKAGES = {
    'Ubuntu': ['python-pip', 'python-setuptools', 'collectd', 'unzip', 'curl'],
    'Debian GNU/Linux': ['python-pip', 'python-setuptools', 'collectd', 'unzip', 'curl'],
    'Red Hat Enterprise Linux Server': ['python-pip', 'python-setuptools', 'collectd', 'unzip', 'curl', 'collectd-python'],
    'Amazon Linux AMI': ['python-pip', 'python-setuptools', 'collectd', 'unzip', 'curl', 'collectd-python'],
    'CentOS Linux': ['python-pip', 'python-setuptools', 'collectd', 'unzip', 'curl', 'collectd-python'],
    'SLES': ['python-pip', 'python-setuptools', 'collectd', 'unzip', 'curl', 'collectd-plugin-python'],
}


LINUX_DISTRIBUTION_TO_OCI_CONF_FILE = {
    'Ubuntu': '/etc/collectd/collectd.conf.d/oci.conf',
    'Debian GNU/Linux': '/etc/collectd/collectd.conf.d/oci.conf',
    'Red Hat Enterprise Linux Server': '/etc/collectd.d/oci.conf',
    'Amazon Linux AMI': '/etc/collectd.d/oci.conf',
    'CentOS Linux': '/etc/collectd.d/oci.conf',
    'SLES': '/etc/collectd/oci.conf',
}


class InstallationFailedException(Exception):
    pass


class Color(object):
    RED = '\033[91m'
    GREEN = '\033[92m'
    END = '\033[0m'

    @classmethod
    def red(cls, string):
        return cls.RED + string + cls.END

    @classmethod
    def green(cls, string):
        return cls.GREEN + string + cls.END


class Command(object):
    SUCCESS = 0
    OK = '... ' + Color.green('OK')
    NOT_OK = '... ' + Color.red('NOT OK')
    INVALID_COMMAND_ERROR_MSG = Color.red("ERROR: Could not execute the following command: {command}.")
    ERROR_MSG = Color.red("Installation cancelled due to an error.\n"
                          "Executed command: '{command}'.\n"
                          "Error output: '{error_output}'.")

    def __init__(self, command, message, exit_on_failure=True, shell=False, print_command=False):
        self.message = message
        self.stdout = ''
        self.stderr = ''
        self._command = command
        self._process = None
        self._shell = shell
        self._exit_on_failure = exit_on_failure
        self._print_command = print_command

    @property
    def was_successful(self):
        return self._process and self._process.returncode is self.SUCCESS

    def run(self):
        if self._print_command:
            print self._command
        print self.message,
        try:
            self._process = self._get_process()
            self._capture_outputs()
        except OSError:
            self.stderr = self.INVALID_COMMAND_ERROR_MSG.format(command=self._command)
        finally:
            self._output_command_status()
        if not self.was_successful and self._exit_on_failure:
            raise InstallationFailedException(self.ERROR_MSG.format(command=self._command, error_output=self.stderr))

    def _get_process(self):
        command = self._command
        if not self._shell:
            command = shlex.split(self._command)
        return subprocess.Popen(command, shell=self._shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _capture_outputs(self):
        stdout, stderr = self._process.communicate()
        self.stdout = str(stdout).strip()
        self.stderr = str(stderr).strip()

    def _output_command_status(self):
        result = self.NOT_OK
        if self.was_successful:
            result = self.OK
        print result


def remove_double_quotes(string):
    if string.startswith('"') and string.endswith('"'):
        return string[1:len(string)-1]
    return string


def detect_linux_release():
    global LINUX_DISTRIBUTION, LINUX_VERSION_ID
    content = ''
    for release_file in glob.glob("/etc/*-release"):
        with open(release_file) as fd:
            content += fd.read()
    for line in content.splitlines():
        if line.startswith('NAME='):
            LINUX_DISTRIBUTION = remove_double_quotes(line[5:])
        elif line.startswith('VERSION_ID='):
            LINUX_VERSION_ID = remove_double_quotes(line[11:])


def create_directory(directory):
    if os.path.exists(directory):
        return
    try:
        os.makedirs(directory)
    except OSError as ex:
        raise InstallationFailedException("Could not create directory: {}. Cause: {}".format(directory, str(ex)))


def exit_with_unsupported_linux():
    exit(Color.red('Unsupported Linux distribution ' + LINUX_DISTRIBUTION + ' with version ' + LINUX_VERSION_ID))


def run_linux_distribution_commands():
    if LINUX_DISTRIBUTION == 'Red Hat Enterprise Linux Server' \
        or LINUX_DISTRIBUTION == 'Amazon Linux AMI' \
            or LINUX_DISTRIBUTION == 'CentOS Linux':
            if LINUX_DISTRIBUTION == 'Amazon Linux AMI' or LINUX_VERSION_ID >= '7':
                print DOWNLOAD_EPEL_RELEASE_7_RPM_COMMAND
                Command(DOWNLOAD_EPEL_RELEASE_7_RPM_COMMAND, "Downloading EPEL 7 release RPM").run()
                command = YUM_INSTALL_COMMAND + DOWNLOADED_EPEL_RELEASE_7_RPM
                Command(command, 'Installing EPEL 7 release', exit_on_failure=False).run()
            else:
                exit_with_unsupported_linux()
    elif LINUX_DISTRIBUTION == 'Ubuntu' or LINUX_DISTRIBUTION == 'Debian GNU/Linux':
        Command('apt-get install -y software-properties-common', 'Installing software-properties-common', exit_on_failure=False).run()
        Command('apt-add-repository -y universe', 'Adding universe repository', exit_on_failure=False).run()
        Command('apt-get update', 'Updating repository', exit_on_failure=False).run()
    elif LINUX_DISTRIBUTION == 'SLES':
        Command('zypper addrepo http://download.opensuse.org/repositories/server:/monitoring/openSUSE_Leap_42.2/server:monitoring.repo', \
            'Adding server monitoring repository', exit_on_failure=False).run()
        Command('zypper --no-gpg-checks --non-interactive update', 'Updating repository', exit_on_failure=False).run()
    else:
        exit_with_unsupported_linux()


def check_enhanced_security():
    if LINUX_DISTRIBUTION == 'Red Hat Enterprise Linux Server' \
            or LINUX_DISTRIBUTION == 'Amazon Linux AMI' \
            or LINUX_DISTRIBUTION == 'CentOS Linux':
        if LINUX_VERSION_ID >= '7' or LINUX_DISTRIBUTION == 'Amazon Linux AMI':
            command = Command('getenforce', 'Checking SELinux setting', exit_on_failure=True)
            command.run()
            result = command.stdout.strip()
            if result == 'Enforcing':
                exit(Color.red("Error: SELinux is not supported."))
        else:
            return


def run_collectd_service():
    if LINUX_DISTRIBUTION == 'Red Hat Enterprise Linux Server' \
            or LINUX_DISTRIBUTION == 'CentOS Linux':
        if float(LINUX_VERSION_ID) >= 7:
            Command('systemctl enable collectd', 'Enable collectd service').run()
            Command('systemctl restart collectd', 'Running collectd service').run()
        else:
            exit_with_unsupported_linux()
    elif LINUX_DISTRIBUTION == 'SLES':
        with open('/etc/collectd.conf', 'a') as file:
            file.write('Include "/etc/collectd"\n')
        Command('systemctl enable collectd', 'Enable collectd service').run()
        Command('systemctl restart collectd', 'Running collectd service').run()
    elif LINUX_DISTRIBUTION == 'Amazon Linux AMI':
        Command('chkconfig --add /etc/rc.d/init.d/collectd', 'Add collectd service').run()
        Command('chkconfig --level 2345 collectd on', 'Enable collectd service').run()
        Command('service collectd restart', 'Running collectd service').run()
    elif LINUX_DISTRIBUTION == 'Ubuntu' or LINUX_DISTRIBUTION == 'Debian GNU/Linux':
        Command('service collectd restart', 'Running collectd service').run()
    else:
        exit_with_unsupported_linux()


def install_packages():
    command = LINUX_DISTRIBUTION_TO_INSTALLER[LINUX_DISTRIBUTION] + \
        ' '.join(LINUX_DISTRIBUTION_TO_DEPENDENT_PACKAGES[LINUX_DISTRIBUTION])
    Command(command, "Installing dependent packages", print_command=True).run()


def install_python_packages(packages):
    command = 'pip install --quiet --upgrade --force-reinstall ' + \
        '--trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org ' + \
        ' '.join(packages)
    Command(command, "Installing python packages", exit_on_failure=True, print_command=True).run()


def initialize_configuration():
    print 'Unzipping ' + DOWNLOADED_PLUGIN_ZIP_FILE + '...'
    with zipfile.ZipFile(DOWNLOADED_PLUGIN_ZIP_FILE, "r") as zip_ref:
        zip_ref.extractall(path=TEMP_DIRECTORY)
    oci_conf_file = LINUX_DISTRIBUTION_TO_OCI_CONF_FILE[LINUX_DISTRIBUTION]
    if os.path.isfile(oci_conf_file):
        shutil.copy2(oci_conf_file, oci_conf_file + '.save')
    with open(PLUGIN_UNZIPPED_DIRECTORY + '/src/config/oci.conf') as fread, \
            open(oci_conf_file, 'w') as fwrite:
        for line in fread:
            if 'OCI_HOST_NAME' in line:
                line = line.replace('OCI_HOST_NAME', OCI_HOST_NAME)
            elif 'OCI_INTEGRATION_TOKEN' in line:
                line = line.replace('OCI_INTEGRATION_TOKEN', OCI_INTEGRATION_TOKEN)
            elif 'DEFAULT_REPORT_INTERVAL' in line:
                line = line.replace('DEFAULT_REPORT_INTERVAL', str(REPORT_INTERVAL_SECONDS))
            elif 'DEFAULT_FAILED_REPORT_QUEUE_SIZE' in line:
                line = line.replace('DEFAULT_FAILED_REPORT_QUEUE_SIZE', str(FAILED_REPORT_QUEUE_SIZE))
            elif 'DEFAULT_AGGREGATION_TYPE' in line:
                line = line.replace('DEFAULT_AGGREGATION_TYPE', AGGREGATION_TYPE)
            elif 'DEFAULT_PLUGINS' in line:
                line = line.replace('DEFAULT_PLUGINS', PLUGINS)
            elif 'DEFAULT_LOGGING_LEVEL' in line:
                line = line.replace('DEFAULT_LOGGING_LEVEL', str(LOGGING_LEVEL))
            fwrite.write(line)


def install_plugin():
    try:
        detect_linux_release()
        if LINUX_DISTRIBUTION == '' or LINUX_VERSION_ID == '':
            raise InstallationFailedException(
                "Cannot detect Linux distribution {} or version {}".format(LINUX_DISTRIBUTION, LINUX_VERSION_ID))
        if LINUX_DISTRIBUTION not in LINUX_DISTRIBUTION_TO_INSTALLER.keys():
            exit_with_unsupported_linux()
        print 'Running Linux with distribution ' + LINUX_DISTRIBUTION + ' and version ' + LINUX_VERSION_ID
        check_enhanced_security()
        create_directory(TEMP_DIRECTORY)
        shutil.rmtree(PLUGIN_UNZIPPED_DIRECTORY, ignore_errors=True)
        create_directory(COLLECTD_OCI_PLUGIN_DIRECTORY)
        run_linux_distribution_commands()
        install_packages()
        install_python_packages(PYTHON_PACKAGES)
        Command(DOWNLOAD_COLLECTD_OCI_PLUGIN_COMMAND, "Downloading collectd-oci-plugin", print_command=True).run()
        initialize_configuration()
        copy_tree(PLUGIN_UNZIPPED_DIRECTORY + '/src/modules', COLLECTD_OCI_PLUGIN_DIRECTORY + '/modules')
        shutil.copy2(PLUGIN_UNZIPPED_DIRECTORY + '/src/oci_write_plugin.py', COLLECTD_OCI_PLUGIN_DIRECTORY)
        run_collectd_service()
    finally:
        shutil.rmtree(PLUGIN_UNZIPPED_DIRECTORY, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='Script for custom installation process for collectd NetApp OnCommand Insight plugin'
    )
    parser.add_argument(
        '--host-name',
        required=True,
        help='OCI host name or IP address to send collectd integration data',
        metavar='HOST_NAME',
        default=None
    )
    parser.add_argument(
        '--token',
        required=True,
        help='The token as a key for OCI integration data',
        metavar='TOKEN',
        default=None
    )
    parser.add_argument(
        '--interval',
        required=False,
        help='The interval in seconds to report aggregated collected data into OCI',
        type=int,
        choices=range(60, 3601),
        metavar='[60,3600]',
        default=60
    )
    parser.add_argument(
        '--queue-size',
        required=False,
        help='The queue size to save failed report data for retry, the default is 0 to disable it',
        type=int,
        choices=range(0, 10001),
        metavar='[0,10000]',
        default=0
    )
    parser.add_argument(
        '--aggregation-type',
        required=False,
        help='The aggregation type for guaged value',
        choices=['average', 'minimum', 'maximum', 'last'],
        default='average'
    )
    parser.add_argument(
        '--plugins',
        required=False,
        help='The collectd plugins to be reported into OCI integration data, '
             'it is comma separated e.g. cpu,memory',
        metavar='PLUGINS',
        default='cpu,memory'
    )
    parser.add_argument(
        '--logging-level',
        required=False,
        help='The logging level',
        choices=['debug', 'info', 'warning', 'error'],
        default='info'
    )

    global OCI_HOST_NAME, OCI_INTEGRATION_TOKEN, REPORT_INTERVAL_SECONDS, FAILED_REPORT_QUEUE_SIZE, \
        AGGREGATION_TYPE, PLUGINS, LOGGING_LEVEL
    args = parser.parse_args()
    OCI_HOST_NAME = args.host_name
    OCI_INTEGRATION_TOKEN = args.token
    REPORT_INTERVAL_SECONDS = args.interval
    FAILED_REPORT_QUEUE_SIZE = args.queue_size
    AGGREGATION_TYPE = args.aggregation_type
    PLUGINS = args.plugins
    LOGGING_LEVEL = args.logging_level

    install_plugin()


if __name__ == "__main__":
    if os.getuid() != ROOT_UID:
        exit(Color.red("Error: this script must be executed with elevated permissions."))
    try:
        main()
    except InstallationFailedException as e:
        exit(Color.red(str(e)))
