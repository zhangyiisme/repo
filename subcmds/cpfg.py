#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author: zoujc0522@thundersoft.com
# cherry pick from gerrit,
#    if it is merge commit, then checkout to it.

import sys
import os
from command import Command
import json
from urllib2 import urlopen
import re

class Cpfg(Command):
    helpSummary = "cherry pick from gerrit"

    def _Options(self, p, show_smart=True):
        p.add_option('-c','--changeids',
                dest='changeids', action='store',
                help="Change-ID")
        p.add_option('-u','--USER',
                dest='user', action='store',
                help="gerrit login name")
        p.add_option('-g','--URL',
                dest='gerrit_url', action='store',
                help="gerrit url")
        p.add_option('--host',
                dest='gerrit_host', action='store',
                help="gerrit host")
        p.add_option('--port',
                dest='gerrit_port', action='store',
                help="gerrit port", default="29418")
        p.add_option('-m','--MERGE',
                dest='ck_merge', action='store_true',
                help="cherry pick merge commit")


    def git_clean(self):
        p = os.popen('git status --porcelain')
        git_status = p.read()
        e = p.close()
        if git_status == '' and e is None:
            return True
        return False


    def query_gerrit(self, gerrit_url,gerrit_host,gerrit_port, user, changeid):
        patchset_number = False
        if changeid.find(',') > 0:
            patchset_number = int(changeid.split(',')[1])
            changeid = changeid.split(',')[0]
        try:
            f = urlopen(gerrit_url + '/ssh_info')
            ssh_info = f.read().split()
            if len(ssh_info) != 2:
                #sys.exit("can't get ssh_info from %s" %(gerrit_url))
                print >> sys.stderr, 'WARN: can not parse %s' %(gerrit_url)
                print >> sys.stderr, 'WARN: user %s:%s' %(gerrit_host,gerrit_port)
            ip = ssh_info[0] if len(ssh_info) == 2 else gerrit_host
            port = ssh_info[1] if len(ssh_info) == 2 else gerrit_port
        except Exception as e:
            ip = gerrit_host
            port = gerrit_port

        if patchset_number:
            query_cmd = 'ssh -p %s %s@%s gerrit query change:%s --format=JSON --patch-sets' %(port, user, ip, changeid)
        else:
            query_cmd = 'ssh -p %s %s@%s gerrit query change:%s --format=JSON --current-patch-set' %(port, user, ip, changeid)
        p = os.popen(query_cmd)
        query_ret_json = p.read().splitlines()
        e = p.close()
        if e is not None or len(query_ret_json) != 2:
            sys.exit("fatal: Can't find %s in %s (%s:%s)" %(changeid, gerrit_url,gerrit_host,gerrit_port))
        query_ret = json.loads(query_ret_json[0])
        number = query_ret['number']
        status = query_ret['status']
        project = query_ret['project']
        ref = None
        commit_hash = None
        if patchset_number:
            for q in query_ret['patchSets']:
                if int(q['number']) == patchset_number:
                    ref = q['ref']
                    commit_hash = q['revision']
        else:
            ref = query_ret['currentPatchSet']['ref']
            commit_hash = query_ret['currentPatchSet']['revision']
        if ref is None or commit_hash is None:
            sys.exit("Can't get change %s ref infomation" %(changeid))
        sortkey = query_ret.get('sortKey',None)
        fetch_url = 'ssh://%s@%s:%s/%s %s' %(user, ip, port, project, ref)
        workspace = os.path.dirname(self.repodir)
        projs = self.manifest.projects
        for j in self.GetProjects(None, missing_ok=True):
            if j.name == project:
                relpath = j.relpath
                abs_relpath = os.path.join(workspace, relpath)

        if abs_relpath is None:
            sys.exit('fatal: No such project [%s] found in local sources, changid [%s]' %(project, changeid))

        return {'sortkey':sortkey,
                'number':number,
                'project':project,
                'status':status,
                'fetch_url':fetch_url,
                'relpath':relpath,
                'abs_relpath':abs_relpath,
                'commit_hash':commit_hash,
                'changeid':changeid}


    def Execute(self, opt, args):
        workspace = os.path.dirname(self.repodir)
        # get changeID
        if not opt.changeids:
            sys.exit('fatal: changeid (-c) is required.')
        if not opt.user:
            sys.exit('fatal: gerrit login name (-u) is required.')
        if not (opt.gerrit_url or (opt.gerrit_host and opt.gerrit_port)) :
            sys.exit('fatal: gerrit url (-g) is required.')

        query_all = []
        for changeid in opt.changeids.split():
            query_all.append(self.query_gerrit(
              opt.gerrit_url,opt.gerrit_host,opt.gerrit_port, opt.user, changeid))
            #query_all.append(self.query_gerrit(opt.gerrit_url, opt.user, changeid))
        query_all.sort(key = lambda x : x['number'])

        # start cherry pick
        for change in query_all:
            project = change['project']
            abs_relpath = change['abs_relpath']
            commit_hash = change['commit_hash']
            changeid = change['changeid']
            fetch_url = change['fetch_url']
            status = change['status']

            if status == 'MERGED':
                continue

            os.chdir(abs_relpath)
            if not self.git_clean():
                print >> sys.stderr, 'Fatal: [%s] not clean, skip this project.' %(abs_relpath)
                os.system('git status')
                sys.exit(1)

            e_f = os.system('git fetch %s' %(fetch_url))
            if e_f != 0:
                sys.exit("Can't fetch %s" %fetch_url)
            if opt.ck_merge:
                os.system('git checkout -f %s; git clean -fd' %(commit_hash))
            else:
                # is a merge commit?
                m = os.popen('git log -1 --format=short %s' %(commit_hash))
                _cmt_msg = m.read().splitlines()
                m.close()
                if len(_cmt_msg) < 2:
                    print >> sys.stderr, "can't retrive commit's message %s." %(commit_hash)
                    sys.exit(1)
                _x = re.match('^Merge', _cmt_msg[1])
                if _x is not None:
                    print 'This is a merge change %s, just checkout to %s' %(changeid, commit_hash)
                    os.system('git checkout -f %s; git clean -fd' %(commit_hash))
                else:
                    print 'Normally cherry pick %s' %(commit_hash)
                    os.system('git cherry-pick -x %s' %(commit_hash))
            if not self.git_clean():
                print >> sys.stderr, 'Conflicts found:'
                print >> sys.stderr, 'project path: [%s]\nchangeid: [%s]\ncommit_sha1: [%s]' %(abs_relpath, changeid, commit_hash)
                os.system('git status')
                sys.exit(1)
