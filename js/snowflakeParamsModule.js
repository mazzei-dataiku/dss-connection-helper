(function() {
  'use strict';

  var app = angular.module('dataiku.plugins.add-snowflake-variables', []);

  app.controller('snowflakeParamsModule', function($scope) {
    // `setup` is populated by paramsPythonSetup.
    // DSS injects it for custom forms.
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

    $scope.ui = {
      rows: cloneRows(setup.rows),
      prefix: setup.defaultPrefix || 'SNOWFLAKE_',
      loadUser: !!setup.prefill,
      saveUser: false,

      onToggleLoadUser: function() {
        if ($scope.ui.loadUser && saved && Array.isArray(saved.rows)) {
          // Prefill by variable_name mapping.
          var byVar = {};
          saved.rows.forEach(function(r) {
            if (r && r.variable_name && r.value !== undefined && r.value !== null && r.value !== '') {
              byVar[r.variable_name] = r.value;
            }
          });
          $scope.ui.rows.forEach(function(r) {
            if (r.variable_name && byVar[r.variable_name] !== undefined) {
              r.value = byVar[r.variable_name];
            }
          });
        }
        $scope.ui.syncSelectionJson();
      },

      syncSelectionJson: function() {
        var payload = {
          version: 1,
          project_key: setup.projectKey,
          variable_prefix: $scope.ui.prefix,
          load_user_variables: !!$scope.ui.loadUser,
          save_user_variables: !!$scope.ui.saveUser,
          rows: $scope.ui.rows
        };
        $scope.config.selection_json = JSON.stringify(payload);
      }
    };

    // Initialize selection_json for first render.
    $scope.ui.syncSelectionJson();
  });
})();

