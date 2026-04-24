%% CLEAN AND CORRECTED SCRIPT
clear all;
close all;
clc;

% Add the CORRECT path (pointing to the 'matlab' subfolder)
addpath('c:\dynare\7.0\matlab');
savepath;

rehash toolboxcache;
cd('C:\Users\HP\Desktop\Fiscal Policy\Fiscal Policy\Psets');
dynare NK_Gali2015_IRFs.mod