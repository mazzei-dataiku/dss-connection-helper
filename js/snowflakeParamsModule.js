define([], function() {
  'use strict';

  // Dataiku custom form controller.
  // DSS injects: $scope.config (to be persisted) and $scope.setup (from paramsPythonSetup).
  return {
    controller: function($scope) {
      var setup = $scope.setup || {};
      var saved = setup.saved || {};

      function cloneRows(rows) {
        return (rows || []).map(function(r) {
          return {
            connection: r.connection,
            key: r.key,
            variable_name: r.variable_name,
            value: r.value
          };
        });
      }

      function prefillFromSaved(rows) {
        if (!saved || !Array.isArray(saved.rows)) return;
        var byVar = {};
        saved.rows.forEach(function(r) {
          if (!r) return;
          if (!r.variable_name) return;
          if (r.value === undefined || r.value === null || r.value === '') return;
          byVar[r.variable_name] = r.value;
        });
        rows.forEach(function(r) {
          if (r.variable_name && byVar[r.variable_name] !== undefined) {
            r.value = byVar[r.variable_name];
          }
        });
      }

      $scope.ui = {
        rows: cloneRows(setup.rows),
        prefix: setup.defaultPrefix || 'SNOWFLAKE_',
        loadUser: !!setup.prefill,
        saveUser: false
      };

      $scope.ui.syncSelectionJson = function() {
        var payload = {
          version: 1,
          project_key: setup.projectKey,
          variable_prefix: $scope.ui.prefix,
          load_user_variables: !!$scope.ui.loadUser,
          save_user_variables: !!$scope.ui.saveUser,
          rows: $scope.ui.rows
        };
        $scope.config.selection_json = JSON.stringify(payload);
      };

      $scope.ui.onToggleLoadUser = function() {
        if ($scope.ui.loadUser) {
          prefillFromSaved($scope.ui.rows);
        }
        $scope.ui.syncSelectionJson();
      };

      // Initialize defaults
      if ($scope.ui.loadUser) {
        prefillFromSaved($scope.ui.rows);
      }
      $scope.ui.syncSelectionJson();

      // If user edits the prefix, recompute variable names.
      $scope.$watch('ui.prefix', function(newPrefix, oldPrefix) {
        if (newPrefix === oldPrefix) return;
        ($scope.ui.rows || []).forEach(function(r) {
          if (!r || !r.key) return;
          r.variable_name = String(newPrefix || '') + String(r.key || '').toUpperCase();
        });
        if ($scope.ui.loadUser) {
          prefillFromSaved($scope.ui.rows);
        }
        $scope.ui.syncSelectionJson();
      });

      // Keep JSON synced as table is edited.
      $scope.$watch('ui.rows', function() {
        $scope.ui.syncSelectionJson();
      }, true);
    }
  };
});

